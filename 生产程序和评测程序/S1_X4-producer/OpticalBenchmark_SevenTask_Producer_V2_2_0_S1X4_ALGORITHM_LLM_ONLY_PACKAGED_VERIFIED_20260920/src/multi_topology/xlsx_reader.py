from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


@dataclass(frozen=True)
class SourceNode:
    source_node_id: int
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class SourceEdge:
    source_edge_id: int
    source: int
    destination: int
    length_km: float


@dataclass(frozen=True)
class ImportedTopology:
    name: str
    source_file: str
    nodes: tuple[SourceNode, ...]
    edges: tuple[SourceEdge, ...]


def _column_index(reference: str) -> int:
    letters = "".join(ch for ch in reference if ch.isalpha())
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter.upper()) - 64
    return value - 1


def _coerce_number(value: Any) -> int | float | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else number


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in item.findall(".//m:t", NS)) for item in root.findall("m:si", NS)]


def _sheet_rows(archive: ZipFile, target: str, shared: list[str]) -> list[list[Any]]:
    path = target.lstrip("/")
    if not path.startswith("xl/"):
        path = "xl/" + path
    root = ET.fromstring(archive.read(path))
    rows: list[list[Any]] = []
    for row in root.findall(".//m:sheetData/m:row", NS):
        values: dict[int, Any] = {}
        for cell in row.findall("m:c", NS):
            index = _column_index(cell.attrib["r"])
            kind = cell.attrib.get("t")
            value_node = cell.find("m:v", NS)
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
            elif value_node is None:
                value = None
            elif kind == "s":
                value = shared[int(value_node.text or "0")]
            elif kind == "b":
                value = value_node.text == "1"
            else:
                value = _coerce_number(value_node.text)
            values[index] = value
        if values:
            rows.append([values.get(i) for i in range(max(values) + 1)])
    return rows


def _tables(path: Path) -> dict[str, list[dict[str, Any]]]:
    with ZipFile(path) as archive:
        shared = _read_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", REL_NS)}
        result: dict[str, list[dict[str, Any]]] = {}
        for sheet in workbook.findall(".//m:sheets/m:sheet", NS):
            name = sheet.attrib["name"]
            rows = _sheet_rows(archive, targets[sheet.attrib[DOC_REL]], shared)
            if not rows:
                result[name] = []
                continue
            headers = [str(value).strip() if value is not None else "" for value in rows[0]]
            result[name] = [
                {headers[index]: value for index, value in enumerate(row) if index < len(headers) and headers[index]}
                for row in rows[1:]
                if any(value is not None for value in row)
            ]
        return result


def read_topology_workbook(path: Path | str) -> ImportedTopology:
    path = Path(path)
    tables = _tables(path)
    node_sheet = next((name for name in tables if name.lower().startswith("nodes_")), None)
    edge_sheet = next((name for name in tables if name.lower().startswith("edges_")), None)
    if node_sheet is None or edge_sheet is None:
        raise ValueError(f"missing Nodes_/Edges_ sheet in {path.name}")
    name = node_sheet.split("_", 1)[1].upper()
    node_by_id: dict[int, SourceNode] = {}
    for row in tables[node_sheet]:
        if row.get("Node_ID") is None:
            continue
        source_id = int(row["Node_ID"])
        node = SourceNode(
            source_id,
            None if row.get("Latitude") is None else float(row["Latitude"]),
            None if row.get("Longitude") is None else float(row["Longitude"]),
        )
        if source_id in node_by_id and node_by_id[source_id] != node:
            raise ValueError(f"ambiguous duplicate Node_ID {source_id} in {path.name}")
        node_by_id[source_id] = node
    edges: list[SourceEdge] = []
    for row in tables[edge_sheet]:
        required = (row.get("Edge_ID"), row.get("Source"), row.get("Destination"), row.get("Computed Length (km)"))
        if any(value is None for value in required):
            continue
        edges.append(SourceEdge(int(required[0]), int(required[1]), int(required[2]), float(required[3])))
    if len(node_by_id) < 2 or not edges:
        raise ValueError(f"empty topology data in {path.name}")
    return ImportedTopology(name, path.name, tuple(node_by_id[key] for key in sorted(node_by_id)), tuple(edges))

