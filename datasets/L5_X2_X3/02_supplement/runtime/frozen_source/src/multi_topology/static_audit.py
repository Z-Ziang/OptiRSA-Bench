from __future__ import annotations

from pathlib import Path
from time import perf_counter

from .audit import (
    audit_source_records,
    build_public_topology,
    length_weighted_normalized_algebraic_connectivity,
)
from .reporting import correlation_matrix, high_correlation_pairs, numeric_summary, write_csv, write_json
from .xlsx_reader import read_topology_workbook


TOPOLOGY_FIELDS = [
    "node_count", "physical_link_count", "directed_link_count", "average_node_degree", "edge_density",
    "average_clustering_coefficient", "diameter_hops", "average_shortest_path_hops",
    "global_edge_connectivity", "bridge_count", "bridge_ratio", "max_normalized_edge_betweenness",
    "normalized_algebraic_connectivity", "average_physical_link_length_km",
    "diameter_physical_length_km", "average_shortest_path_physical_length_km",
]


def run_static_audit(source_dir: Path, audit_root: Path) -> dict:
    all_rows = []
    clean_rows = []
    weighted_rows = []
    anomaly_names = []
    scaling = []
    for path in sorted(source_dir.glob("*.xlsx")):
        started = perf_counter()
        imported = read_topology_workbook(path)
        read_seconds = perf_counter()-started
        source_audit = audit_source_records(imported)
        row = {
            "source_file": path.name, "topology_name": imported.name,
            "raw_node_count": len(imported.nodes), "raw_edge_count": len(imported.edges),
            "clean": source_audit.clean, "connected": source_audit.connected,
            "self_loop_count": len(source_audit.self_loops),
            "duplicate_pair_count": len(source_audit.duplicate_pairs),
            "ambiguous_duplicate_pair_count": len(source_audit.ambiguous_duplicate_pairs),
            "unknown_endpoint_count": len(source_audit.unknown_endpoint_edges),
        }
        if source_audit.clean:
            metric_started = perf_counter()
            physical, _, metrics, private = build_public_topology(imported, "audit_only")
            metric_seconds = perf_counter()-metric_started
            row.update(metrics)
            row.pop("topology_id", None)
            length_edges = [(edge["node_u_id"], edge["node_v_id"], edge["length_km"])
                            for edge in physical["physical_link_records"]]
            weighted = length_weighted_normalized_algebraic_connectivity(len(physical["node_records"]), length_edges)
            row["normalized_algebraic_connectivity_length_weighted_audit"] = weighted
            weighted_rows.append({"topology_name": imported.name,
                                  "p0r1_unweighted": metrics["normalized_algebraic_connectivity"],
                                  "length_weighted_audit": weighted})
            clean_rows.append(dict(row))
            scaling.append({"topology_name": imported.name, "node_count": metrics["node_count"],
                            "physical_link_count": metrics["physical_link_count"],
                            "xlsx_read_seconds": read_seconds, "topology_metric_seconds": metric_seconds})
            write_json(audit_root/"topology_105"/"private_source_mappings"/f"{imported.name}.json", private)
        else:
            anomaly_names.append(imported.name)
            write_json(audit_root/"source_anomalies"/f"{imported.name}.json", {
                "source_file": path.name, "topology_name": imported.name, **source_audit.as_dict()
            })
        all_rows.append(row)
    write_csv(audit_root/"topology_105"/"topology_105_all.csv", all_rows)
    write_csv(audit_root/"topology_105"/"topology_98_clean.csv", clean_rows)
    write_csv(audit_root/"scaling"/"topology_static_scaling.csv", scaling)
    summary = numeric_summary(clean_rows, TOPOLOGY_FIELDS)
    pearson = correlation_matrix(clean_rows, TOPOLOGY_FIELDS, "PEARSON")
    spearman = correlation_matrix(clean_rows, TOPOLOGY_FIELDS, "SPEARMAN")
    write_csv(audit_root/"metric_sufficiency"/"topology_metric_summary.csv", summary)
    write_csv(audit_root/"metric_sufficiency"/"topology_metric_pearson.csv", pearson)
    write_csv(audit_root/"metric_sufficiency"/"topology_metric_spearman.csv", spearman)
    high = {
        "pearson": high_correlation_pairs(pearson, TOPOLOGY_FIELDS, 0.90),
        "spearman": high_correlation_pairs(spearman, TOPOLOGY_FIELDS, 0.90),
    }
    write_json(audit_root/"metric_sufficiency"/"topology_high_correlation_pairs.json", high)
    write_json(audit_root/"topology_105"/"normalized_algebraic_connectivity_audit.json", {
        "public_field_mode": "UNWEIGHTED_NORMALIZED_LAPLACIAN_SECOND_EIGENVALUE",
        "audit_only_mode": "LENGTH_WEIGHTED_NORMALIZED_LAPLACIAN_SECOND_EIGENVALUE",
        "audit_only_values": weighted_rows,
        "topologybench_public_range_audit": {
            "minimum": min(row["length_weighted_audit"] for row in weighted_rows),
            "maximum": max(row["length_weighted_audit"] for row in weighted_rows),
        },
        "required_spot_checks": [row for row in weighted_rows
                                 if row["topology_name"] in {"LAYER42", "SANET", "GERMANY50"}],
        "public_schema_modified": False,
    })
    return {
        "workbook_count": len(all_rows), "clean_count": len(clean_rows),
        "anomaly_count": len(anomaly_names), "anomaly_names": sorted(anomaly_names),
        "clean_rows": clean_rows, "weighted_rows": weighted_rows,
    }
