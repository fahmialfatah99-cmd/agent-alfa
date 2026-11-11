"""Ekspor graph pengetahuan (JSON/GraphML)."""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import init_graph_db
from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

def export_knowledge_graph(
    format_type: str = "jsonld",
    db_path: str | None = None,
    user_id: int = 1,
) -> dict[str, Any] | str:
    """
    Mengekspor seluruh Knowledge Graph ke format enterprise terbuka:
    - 'jsonld': JSON-LD Schema.org graph object
    - 'graphml': XML GraphML standard (Gephi, Cytoscape, NetworkX compatible)
    - 'cypher': OpenCypher scripts (Neo4j, Memgraph, Kùzu compatible)
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    conn = sqlite3.connect(target_db, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        entities = conn.execute(
            "SELECT DISTINCT name, entity_type, description, source_doc FROM graph_entities WHERE user_id = ?",
            (user_id,),
        ).fetchall()

        relations = conn.execute(
            "SELECT id, source_entity, relation, target_entity, weight, source_doc, evidence FROM graph_relations WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    node_set: dict[str, dict[str, str]] = {}
    for e in entities:
        node_set[e["name"]] = {
            "name": e["name"],
            "type": e["entity_type"] or "Concept",
            "description": e["description"] or "",
            "source_doc": e["source_doc"] or "",
        }
    for r in relations:
        if r["source_entity"] not in node_set:
            node_set[r["source_entity"]] = {
                "name": r["source_entity"],
                "type": "Concept",
                "description": "",
                "source_doc": r["source_doc"] or "",
            }
        if r["target_entity"] not in node_set:
            node_set[r["target_entity"]] = {
                "name": r["target_entity"],
                "type": "Concept",
                "description": "",
                "source_doc": r["source_doc"] or "",
            }

    fmt = (format_type or "jsonld").lower().strip()

    if fmt == "graphml":
        import html
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"',
            '         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            '         xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">',
            '  <key id="d0" for="node" attr.name="label" attr.type="string"/>',
            '  <key id="d1" for="node" attr.name="type" attr.type="string"/>',
            '  <key id="d2" for="edge" attr.name="relation" attr.type="string"/>',
            '  <key id="d3" for="edge" attr.name="weight" attr.type="double"/>',
            '  <graph id="ALFA_Graph" edgedefault="directed">',
        ]
        for name, meta in node_set.items():
            safe_id = html.escape(name)
            safe_type = html.escape(meta["type"])
            xml_lines.append(
                f'    <node id="{safe_id}">\n'
                f'      <data key="d0">{safe_id}</data>\n'
                f'      <data key="d1">{safe_type}</data>\n'
                f'    </node>'
            )
        for idx, r in enumerate(relations):
            s_id = html.escape(r["source_entity"])
            t_id = html.escape(r["target_entity"])
            rel = html.escape(r["relation"])
            w = float(r["weight"] or 1.0)
            xml_lines.append(
                f'    <edge id="e{idx}" source="{s_id}" target="{t_id}">\n'
                f'      <data key="d2">{rel}</data>\n'
                f'      <data key="d3">{w}</data>\n'
                f'    </edge>'
            )
        xml_lines.append("  </graph>")
        xml_lines.append("</graphml>")
        return "\n".join(xml_lines)

    if fmt == "cypher":
        cypher_lines = ["// ALFA Knowledge Graph OpenCypher Export"]
        for name, meta in node_set.items():
            clean_name = name.replace("'", "\\'")
            clean_type = re.sub(r"[^A-Za-z0-9_]", "", meta["type"]) or "Concept"
            cypher_lines.append(f"MERGE (n:{clean_type} {{name: '{clean_name}'}});")
        for r in relations:
            s = r["source_entity"].replace("'", "\\'")
            t = r["target_entity"].replace("'", "\\'")
            rel = re.sub(r"[^A-Za-z0-9_]", "_", r["relation"]).upper() or "RELATES_TO"
            w = float(r["weight"] or 1.0)
            cypher_lines.append(
                f"MATCH (a {{name: '{s}'}}), (b {{name: '{t}'}}) "
                f"MERGE (a)-[:{rel} {{weight: {w}}}]->(b);"
            )
        return "\n".join(cypher_lines)

    # Default: JSON-LD
    graph_nodes: list[dict[str, Any]] = []
    for name, meta in node_set.items():
        graph_nodes.append({
            "@id": f"alfa:entity/{name}",
            "@type": meta["type"] or "Thing",
            "name": name,
            "description": meta["description"],
            "sourceDoc": meta["source_doc"],
        })
    for idx, r in enumerate(relations):
        graph_nodes.append({
            "@id": f"alfa:relation/{r['id'] or idx}",
            "@type": "alfa:Relationship",
            "source": f"alfa:entity/{r['source_entity']}",
            "target": f"alfa:entity/{r['target_entity']}",
            "relation": r["relation"],
            "weight": float(r["weight"] or 1.0),
            "sourceDoc": r["source_doc"] or "",
            "evidence": r["evidence"] or "",
        })
    return {
        "@context": {
            "@vocab": "https://schema.org/",
            "alfa": "https://alfa.os/graph/",
            "source": {"@type": "@id"},
            "target": {"@type": "@id"},
            "relation": "alfa:relation",
            "weight": "alfa:weight",
            "sourceDoc": "alfa:sourceDoc",
            "evidence": "alfa:evidence",
        },
        "@graph": graph_nodes,
    }
