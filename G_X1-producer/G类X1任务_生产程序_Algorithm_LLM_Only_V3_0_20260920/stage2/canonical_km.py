from __future__ import annotations

import csv
import hashlib
import json
import math
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from gx1.topology import load_topology


EXPECTED_TOPOLOGIES: tuple[dict[str, Any], ...] = (
    {
        "topology_id": "topologybench_netrail",
        "display_name": "NETRAIL",
        "source_family": "TopologyBench_real",
        "scale_bin": "5-10",
        "node_count": 7,
        "physical_link_count": 10,
    },
    {
        "topology_id": "topologybench_elibackbone",
        "display_name": "ELIBACKBONE",
        "source_family": "TopologyBench_real",
        "scale_bin": "11-29",
        "node_count": 20,
        "physical_link_count": 30,
    },
    {
        "topology_id": "topologybench_jpn48",
        "display_name": "JPN48",
        "source_family": "TopologyBench_real",
        "scale_bin": "30-59",
        "node_count": 48,
        "physical_link_count": 82,
    },
    {
        "topology_id": "topologybench_conus75",
        "display_name": "CONUS75",
        "source_family": "TopologyBench_real",
        "scale_bin": "60-100",
        "node_count": 75,
        "physical_link_count": 99,
    },
    {
        "topology_id": "topohub_gabriel_125_0",
        "display_name": "topohub_gabriel_125_0",
        "source_family": "TopoHub_Gabriel_controlled",
        "scale_bin": "101-142",
        "node_count": 125,
        "physical_link_count": 220,
    },
    {
        "topology_id": "topohub_gabriel_175_2",
        "display_name": "topohub_gabriel_175_2",
        "source_family": "TopoHub_Gabriel_controlled",
        "scale_bin": "143-200",
        "node_count": 175,
        "physical_link_count": 340,
    },
    {
        "topology_id": "topohub_gabriel_250_3",
        "display_name": "topohub_gabriel_250_3",
        "source_family": "TopoHub_Gabriel_controlled",
        "scale_bin": "201-300",
        "node_count": 250,
        "physical_link_count": 490,
    },
    {
        "topology_id": "topohub_gabriel_375_3",
        "display_name": "topohub_gabriel_375_3",
        "source_family": "TopoHub_Gabriel_controlled",
        "scale_bin": "301-400",
        "node_count": 375,
        "physical_link_count": 757,
    },
    {
        "topology_id": "topohub_gabriel_450_9",
        "display_name": "topohub_gabriel_450_9",
        "source_family": "TopoHub_Gabriel_controlled",
        "scale_bin": "401-500",
        "node_count": 450,
        "physical_link_count": 883,
    },
)

EXPECTED_BY_ID = {row["topology_id"]: row for row in EXPECTED_TOPOLOGIES}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_crc(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        bad_entry = archive.testzip()
        return {
            "path": str(path),
            "entry_count": len(archive.infolist()),
            "crc_pass": bad_entry is None,
            "bad_entry": bad_entry,
        }


def _physical_dir(package_root: Path) -> Path:
    nested = package_root / "01_canonical_physical"
    return nested if nested.is_dir() else package_root


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_rows(package_root: Path) -> dict[str, dict[str, str]]:
    path = package_root / "TOPOLOGY_CANONICAL_MANIFEST.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["topology_id"]: row for row in csv.DictReader(handle)}


def _verify_hash_manifest(package_root: Path) -> dict[str, Any]:
    path = package_root / "SHA256SUMS.txt"
    if not path.exists():
        return {"present": False, "pass": True, "checked": 0, "mismatches": []}
    mismatches: list[dict[str, str]] = []
    checked = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        parts = text.split(None, 1)
        if len(parts) != 2:
            mismatches.append({"line": str(line_number), "reason": "malformed"})
            continue
        expected, relative = parts
        target = package_root / relative.replace("/", "\\")
        checked += 1
        if not target.exists():
            mismatches.append({"path": relative, "reason": "missing", "expected": expected})
            continue
        actual = sha256_file(target)
        if actual.lower() != expected.lower():
            mismatches.append({"path": relative, "reason": "sha256_mismatch", "expected": expected, "actual": actual})
    return {"present": True, "pass": not mismatches, "checked": checked, "mismatches": mismatches}


def _schema_errors(data: dict[str, Any], schema_path: Path | None) -> list[str]:
    if schema_path is not None and schema_path.exists():
        try:
            import jsonschema  # type: ignore

            schema = _read_json(schema_path)
            validator = jsonschema.Draft202012Validator(schema)
            return [error.message for error in sorted(validator.iter_errors(data), key=str)]
        except ImportError:
            pass
    required = {"topology_id", "source_type", "node_records", "physical_link_records"}
    errors: list[str] = []
    if set(data) != required:
        errors.append(f"canonical physical top-level keys differ: {sorted(data)}")
    if not isinstance(data.get("node_records"), list):
        errors.append("node_records is not an array")
    if not isinstance(data.get("physical_link_records"), list):
        errors.append("physical_link_records is not an array")
    return errors


def _connected(nodes: list[int], edges: list[tuple[int, int]]) -> bool:
    if not nodes:
        return False
    adjacency: dict[int, set[int]] = {node: set() for node in nodes}
    for u, v in edges:
        adjacency.setdefault(u, set()).add(v)
        adjacency.setdefault(v, set()).add(u)
    seen = {nodes[0]}
    stack = [nodes[0]]
    while stack:
        node = stack.pop()
        for neighbour in adjacency[node]:
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return len(seen) == len(nodes)


def _bridge_count(nodes: list[int], edges: list[tuple[int, int]]) -> int:
    adjacency: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for index, (u, v) in enumerate(edges):
        adjacency[u].append((v, index))
        adjacency[v].append((u, index))
    discovery: dict[int, int] = {}
    low: dict[int, int] = {}
    time = 0
    bridges = 0

    def visit(node: int, parent_edge: int) -> None:
        nonlocal time, bridges
        time += 1
        discovery[node] = low[node] = time
        for neighbour, edge_id in adjacency[node]:
            if edge_id == parent_edge:
                continue
            if neighbour not in discovery:
                visit(neighbour, edge_id)
                low[node] = min(low[node], low[neighbour])
                if low[neighbour] > discovery[node]:
                    bridges += 1
            else:
                low[node] = min(low[node], discovery[neighbour])

    for node in nodes:
        if node not in discovery:
            visit(node, -1)
    return bridges


def _stoer_wagner_edge_connectivity(nodes: list[int], edges: list[tuple[int, int]]) -> int:
    """Compute the undirected global unit-capacity min-cut for fallback cases."""
    if len(nodes) <= 1:
        return 0
    active = list(nodes)
    weights: dict[int, dict[int, int]] = {u: {v: 0 for v in nodes} for u in nodes}
    for u, v in edges:
        weights[u][v] += 1
        weights[v][u] += 1
    best = math.inf
    while len(active) > 1:
        used: set[int] = set()
        connection = {node: 0 for node in active}
        previous: int | None = None
        for phase_index in range(len(active)):
            selectable = [node for node in active if node not in used]
            selected = max(selectable, key=lambda node: (connection[node], -node))
            if phase_index == len(active) - 1:
                best = min(best, connection[selected])
                if previous is not None:
                    for node in active:
                        if node == previous or node == selected:
                            continue
                        weights[previous][node] += weights[selected][node]
                        weights[node][previous] = weights[previous][node]
                    active.remove(selected)
                break
            used.add(selected)
            previous = selected
            for node in active:
                if node not in used:
                    connection[node] += weights[selected][node]
    return int(best)


def _topology_properties(data: dict[str, Any], path: Path, expected: dict[str, Any], schema_path: Path | None, manifest_row: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    schema_errors = _schema_errors(data, schema_path)
    errors.extend(f"schema: {error}" for error in schema_errors)
    nodes = [int(row["node_id"]) for row in data.get("node_records", []) if isinstance(row, dict) and "node_id" in row]
    link_records = data.get("physical_link_records", [])
    edges: list[tuple[int, int]] = []
    self_loops: list[int] = []
    duplicate_edges: list[list[int]] = []
    seen_edges: set[tuple[int, int]] = set()
    link_ids: list[int] = []
    lengths: list[float] = []
    for record in link_records:
        if not isinstance(record, dict):
            errors.append("physical link record is not an object")
            continue
        try:
            link_id = int(record["physical_link_id"])
            u = int(record["node_u_id"])
            v = int(record["node_v_id"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid physical link record: {exc}")
            continue
        link_ids.append(link_id)
        edges.append((u, v))
        if u == v:
            self_loops.append(link_id)
        key = tuple(sorted((u, v)))
        if key in seen_edges:
            duplicate_edges.append([u, v])
        seen_edges.add(key)
        if "length_km" not in record:
            errors.append(f"link {link_id} missing length_km")
        else:
            try:
                value = float(record["length_km"])
                lengths.append(value)
                if not math.isfinite(value) or value <= 0:
                    errors.append(f"link {link_id} length_km is not positive finite")
            except (TypeError, ValueError):
                errors.append(f"link {link_id} length_km is not numeric")
    if nodes != list(range(len(nodes))):
        errors.append("node_id sequence is not zero-based contiguous")
    if link_ids != list(range(len(link_ids))):
        errors.append("physical_link_id sequence is not zero-based contiguous")
    if any(u > v for u, v in edges):
        errors.append("canonical physical endpoint order is not ascending")
    if len(nodes) != expected["node_count"]:
        errors.append(f"node count expected {expected['node_count']} actual {len(nodes)}")
    if len(edges) != expected["physical_link_count"]:
        errors.append(f"physical link count expected {expected['physical_link_count']} actual {len(edges)}")
    if self_loops:
        errors.append(f"self loops: {self_loops}")
    if duplicate_edges:
        errors.append(f"duplicate undirected edges: {duplicate_edges[:5]}")
    is_connected = _connected(nodes, edges)
    if not is_connected:
        errors.append("graph is disconnected")
    bridge_count = _bridge_count(nodes, edges) if nodes else 0
    degrees: dict[int, int] = {node: 0 for node in nodes}
    for u, v in edges:
        if u in degrees:
            degrees[u] += 1
        if v in degrees:
            degrees[v] += 1
    if bridge_count:
        edge_connectivity = 1
    elif degrees and min(degrees.values()) <= 2:
        edge_connectivity = min(degrees.values())
    else:
        edge_connectivity = _stoer_wagner_edge_connectivity(nodes, edges)
    manifest_family = manifest_row.get("source_family")
    if manifest_family and manifest_family != expected["source_family"]:
        errors.append(f"source family mismatch: expected {expected['source_family']} actual {manifest_family}")
    manifest_nodes = manifest_row.get("node_count")
    if manifest_nodes and int(manifest_nodes) != len(nodes):
        errors.append("manifest node count mismatch")
    manifest_links = manifest_row.get("physical_link_count")
    if manifest_links and int(manifest_links) != len(edges):
        errors.append("manifest physical link count mismatch")
    actual_sha256 = sha256_file(path)
    manifest_physical_sha256 = manifest_row.get("canonical_physical_sha256")
    manifest_hash_match = True
    if manifest_physical_sha256:
        manifest_hash_match = manifest_physical_sha256.lower() == actual_sha256.lower()
        if not manifest_hash_match:
            errors.append(
                f"canonical physical SHA256 mismatch: manifest={manifest_physical_sha256} actual={actual_sha256}"
            )
    if manifest_row.get("validation_pass") and manifest_row["validation_pass"].lower() != "true":
        errors.append(f"canonical manifest validation_pass is not True: {manifest_row['validation_pass']}")
    # A test or an outer orchestration layer may intentionally pass only the
    # nine frozen physical JSON files, without the package manifest.  In that
    # mode the physical bytes are still authoritative, but the source package
    # cannot be used to assert a provenance method that is not present in the
    # directory.  The full canonical package path is checked strictly below
    # against its manifest value.
    method = manifest_row.get("length_method") or "CANONICAL_PHYSICAL_FILE_SUPPLIED_BY_HANDOFF"
    if expected["source_family"] == "TopoHub_Gabriel_controlled" and manifest_row and method != "UNIFORM_GEOMETRY_TO_KM_CALIBRATION":
        errors.append(f"Gabriel length method is not supplied canonical calibration: {method}")
    if expected["source_family"] == "TopologyBench_real" and manifest_row and method not in {"SOURCE_COMPUTED_KM_PRESERVED", "SUPPLIED_CANONICAL_PHYSICAL_LENGTH_KM"}:
        errors.append(f"TopologyBench length method is unexpected: {method}")
    result = {
        **expected,
        "source_type": data.get("source_type"),
        "path": str(path),
        "sha256": actual_sha256,
        "manifest_hash_match": manifest_hash_match,
        "schema_pass": not schema_errors,
        "node_count": len(nodes),
        "physical_link_count": len(edges),
        "self_loops": self_loops,
        "duplicate_undirected_edges": duplicate_edges,
        "connected": is_connected,
        "bridge_count": bridge_count,
        "edge_connectivity": edge_connectivity,
        "two_edge_connected": edge_connectivity >= 2 and is_connected,
        "all_lengths_positive": bool(lengths) and len(lengths) == len(edges) and all(value > 0 and math.isfinite(value) for value in lengths),
        "length_count": len(lengths),
        "mean_length_km": (sum(lengths) / len(lengths)) if lengths else None,
        "min_length_km": min(lengths) if lengths else None,
        "max_length_km": max(lengths) if lengths else None,
        "total_length_km_eligible": bool(lengths) and len(lengths) == len(edges) and all(value > 0 and math.isfinite(value) for value in lengths),
        "length_method": method,
        "gabriel_raw_dist_directly_used_as_km": False,
        "roundtrip_exact": False,
        "manifest_row": manifest_row,
    }
    try:
        loaded = load_topology(path)
        loaded_edges = [(edge.u, edge.v, edge.length_km) for edge in loaded.edges]
        input_edges = [(u, v, float(record["length_km"])) for (u, v), record in zip(edges, link_records)]
        roundtrip_exact = loaded.topology_id == data["topology_id"] and list(loaded.nodes) == nodes and len(loaded_edges) == len(input_edges) and all(
            left[0] == right[0] and left[1] == right[1] and math.isclose(float(left[2]), float(right[2]), rel_tol=0.0, abs_tol=0.0)
            for left, right in zip(loaded_edges, input_edges)
        )
        result["roundtrip_exact"] = roundtrip_exact
        if not roundtrip_exact:
            errors.append("Producer load round-trip changed canonical physical fields")
    except Exception as exc:
        errors.append(f"Producer load failed: {exc}")
    return result, errors


def audit_canonical_package(package_root: Path, outer_handoff_zip: Path | None = None, topology_package_zip: Path | None = None) -> dict[str, Any]:
    package_root = Path(package_root).resolve()
    physical_dir = _physical_dir(package_root)
    manifest_rows = _manifest_rows(package_root)
    schema_path = package_root / "06_contract_reference" / "physical_topology.schema.json"
    errors: list[str] = []
    if not physical_dir.is_dir():
        errors.append(f"canonical physical directory missing: {physical_dir}")
    actual_files = sorted(path.stem for path in physical_dir.glob("*.json")) if physical_dir.is_dir() else []
    expected_ids = [row["topology_id"] for row in EXPECTED_TOPOLOGIES]
    if set(actual_files) != set(expected_ids):
        errors.append(f"topology IDs differ: expected={expected_ids} actual={actual_files}")
    topologies: list[dict[str, Any]] = []
    for expected in EXPECTED_TOPOLOGIES:
        path = physical_dir / f"{expected['topology_id']}.json"
        if not path.exists():
            errors.append(f"missing canonical physical file: {path.name}")
            continue
        try:
            data = _read_json(path)
        except Exception as exc:
            errors.append(f"JSON parse failed {path.name}: {exc}")
            continue
        if data.get("topology_id") != expected["topology_id"]:
            errors.append(f"topology_id mismatch in {path.name}")
        row, row_errors = _topology_properties(data, path, expected, schema_path if schema_path.exists() else None, manifest_rows.get(expected["topology_id"], {}))
        topologies.append(row)
        errors.extend(f"{expected['topology_id']}: {error}" for error in row_errors)
    hash_audit = _verify_hash_manifest(package_root)
    errors.extend(f"package hash manifest: {mismatch}" for mismatch in hash_audit["mismatches"])
    zip_audits: dict[str, Any] = {}
    for label, path in (("outer_handoff", outer_handoff_zip), ("canonical_package", topology_package_zip)):
        if path is not None:
            try:
                zip_audits[label] = {**zip_crc(Path(path)), "sha256": sha256_file(Path(path))}
                if not zip_audits[label]["crc_pass"]:
                    errors.append(f"{label} ZIP CRC failed")
            except Exception as exc:
                zip_audits[label] = {"path": str(path), "pass": False, "error": str(exc)}
                errors.append(f"{label} ZIP audit failed: {exc}")
    preprocessing_validation = package_root / "CANONICAL_PREPROCESSING_VALIDATION.json"
    compatibility_validation = package_root / "CANONICAL_PRODUCER_COMPATIBILITY_VALIDATION.json"
    if preprocessing_validation.exists():
        validation = _read_json(preprocessing_validation)
        if validation.get("expected_topology_count") != 9 or validation.get("actual_topology_count") != 9 or not validation.get("all_validation_pass"):
            errors.append("canonical preprocessing validation evidence is not PASS")
        if not validation.get("gabriel_raw_dist_never_used_directly_as_km", False):
            errors.append("canonical preprocessing evidence does not prove raw Gabriel dist separation")
    if compatibility_validation.exists():
        validation = _read_json(compatibility_validation)
        if not (validation.get("all_json_schema_pass") and validation.get("all_producer_load_pass") and validation.get("all_roundtrip_exact")):
            errors.append("canonical Producer compatibility evidence is not PASS")
    return {
        "pass": not errors,
        "canonical_km_topology_baseline_accepted": not errors,
        "second_scaling_performed": False,
        "source_mode": "DIRECT_SUPPLIED_CANONICAL_PHYSICAL_JSON",
        "package_root": str(package_root),
        "physical_dir": str(physical_dir),
        "expected_topology_count": 9,
        "actual_topology_count": len(topologies),
        "topologies": topologies,
        "package_hash_manifest": hash_audit,
        "zip_audits": zip_audits,
        "errors": errors,
    }


def copy_canonical_package_assets(package_root: Path, destination: Path) -> None:
    """Copy frozen bytes for release evidence; no parse/reserialize is used."""
    import shutil

    package_root = Path(package_root)
    physical = _physical_dir(package_root)
    destination.mkdir(parents=True, exist_ok=True)
    if (package_root / "01_canonical_physical").is_dir():
        # Preserve the supplied package layout and its hash-manifest paths so
        # a release consumer can re-run the same acceptance audit after
        # extraction.  Files are copied byte-for-byte; no JSON is rewritten.
        for source in sorted(package_root.rglob("*")):
            if not source.is_file():
                continue
            target = destination / source.relative_to(package_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    else:
        # A physical-only input directory is useful for unit tests and outer
        # orchestration.  Put those immutable files under the same canonical
        # subdirectory used by the full package, without inventing metadata.
        physical_destination = destination / "01_canonical_physical"
        physical_destination.mkdir(parents=True, exist_ok=True)
        for source in sorted(physical.glob("*.json")):
            shutil.copyfile(source, physical_destination / source.name)


def copy_lineage(package_root: Path, destination: Path) -> None:
    import shutil

    source = Path(package_root) / "04_lineage"
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*.json")):
        shutil.copyfile(path, destination / path.name)
