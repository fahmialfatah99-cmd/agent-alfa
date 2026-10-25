import asyncio
import os
from datetime import datetime
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from alfa.core import database
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, safe_int
from alfa.dashboard.routes.auth import require_admin

router = APIRouter()

# ==================== PIPELINES WORKFLOW ENGINE ====================


@router.get("/api/pipelines")
async def list_pipelines_endpoint():
    """Daftar pipeline workflow yang tersedia."""
    from alfa.pipelines import engine as pl

    return {"status": "success", "pipelines": pl.list_pipelines()}


@router.get("/api/pipelines/{pid}")
async def get_pipeline_endpoint(pid: str):
    from alfa.pipelines import engine as pl

    try:
        return {"status": "success", "pipeline": pl.load_pipeline(pid)}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Pipeline tidak ditemukan."
        ) from None


@router.post("/api/pipelines/{pid}/run")
async def run_pipeline_endpoint(pid: str, request: Request):
    """Jalankan pipeline; body JSON opsional: overrides variabel {"vars": {...}} (hanya admin)."""
    require_admin(request)
    from alfa.pipelines import engine as pl

    try:
        overrides: dict[str, Any] = {}
        try:
            body = await request.json()
            if isinstance(body, dict):
                overrides = body.get("vars") or {}
        except (ValueError, TypeError, RuntimeError):
            pass
        result = await asyncio.wait_for(pl.run_pipeline(pid, overrides), timeout=600)
        return result
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Pipeline tidak ditemukan."
        ) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/pipelines/{pid}")
async def save_pipeline_endpoint(pid: str, request: Request):
    """Simpan/overwrite definisi pipeline dari Canvas Studio (hanya admin)."""
    require_admin(request)
    from alfa.pipelines import engine as pl

    try:
        data = await request.json()
    except (ValueError, TypeError, RuntimeError):
        raise HTTPException(status_code=400, detail="Body harus JSON valid.") from None
    if not isinstance(data, dict) or not data.get("steps"):
        raise HTTPException(status_code=400, detail="Pipeline wajib punya 'steps'.")
    data["id"] = pid
    try:
        path = pl.save_pipeline(data)
        return {"status": "success", "file": os.path.basename(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/pipelines/{pid}/webhook", dependencies=[Depends(require_admin)])
async def pipeline_webhook_endpoint(pid: str, request: Request):
    """Trigger webhook ala n8n: POST di sini menjalankan pipeline."""
    from alfa.pipelines import engine as pl

    try:
        data = pl.load_pipeline(pid)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Pipeline tidak ditemukan."
        ) from None
    secret = ((data.get("trigger") or {}).get("secret") or "").strip()
    if secret:
        provided = (
            request.headers.get("X-Webhook-Key")
            or request.query_params.get("key")
            or ""
        )
        if provided != secret:
            raise HTTPException(status_code=401, detail="Webhook key salah.")
    try:
        payload = await request.json()
    except (ValueError, TypeError, RuntimeError):
        payload = {}
    overrides = {"payload": payload if isinstance(payload, dict) else {"raw": payload}}
    result = await asyncio.wait_for(pl.run_pipeline(pid, overrides), timeout=600)
    return {
        k: result[k]
        for k in ("pipeline", "status", "duration_ms", "outputs")
        if k in result
    }


@router.get("/api/pipelines/{pid}/runs")
async def pipeline_runs_endpoint(pid: str, limit: int = 10):
    """Riwayat eksekusi pipeline terakhir."""
    from alfa.pipelines import engine as pl

    return {"status": "success", "pid": pid, "runs": pl.list_runs(pid, limit)}


@router.post("/api/pipelines/{pid}/enable")
async def pipeline_trigger_toggle_endpoint(pid: str, request: Request):
    """Aktif/matikan trigger jadwal: body {"enabled": true/false} (hanya admin)."""
    require_admin(request)
    from alfa.pipelines import engine as pl

    try:
        data = pl.load_pipeline(pid)
        body = await request.json()
        trig = data.get("trigger") or {}
        trig["type"] = trig.get("type") or "interval"
        trig["minutes"] = int(body.get("minutes", trig.get("minutes", 30)))
        trig["enabled"] = bool(body.get("enabled"))
        data["trigger"] = trig
        pl.save_pipeline(data)
        return {"status": "success", "trigger": trig}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Pipeline tidak ditemukan."
        ) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ==================== MEMORY & SECOND BRAIN ENDPOINTS ====================


@router.get("/api/memory")
async def get_memory_data():
    """Fetch all permanent memory facts and knowledge graph relations."""
    uid = get_primary_user_id()
    memories = await database.get_all_memories(uid)
    kg = database.get_all_knowledge_graph_sync(uid)

    return {
        "status": "success",
        "user_id": uid,
        "total_memories": len(memories),
        "total_kg_relations": len(kg),
        "memories": memories,
        "knowledge_graph": kg,
    }


@router.post("/api/memory/add")
async def add_memory(request: Request, payload: dict[str, Any]):
    """Add a new memory fact or knowledge graph relation (hanya admin)."""
    require_admin(request)
    uid = get_primary_user_id()
    m_type = payload.get("type", "fact")

    if m_type == "fact":
        key = payload.get("key_topic")
        content = payload.get("content")
        cat = payload.get("category", "general")
        if not key or not content:
            raise HTTPException(
                status_code=400, detail="key_topic and content required"
            )
        res: Any = database.save_memory_fact_sync(uid, key, content, cat)
        return {"status": "success", "result": res}
    else:
        entity = payload.get("entity")
        relation = payload.get("relation")
        target = payload.get("target_value")
        cat = payload.get("category", "general")
        tags = payload.get("tags", "")
        if not entity or not relation or not target:
            raise HTTPException(
                status_code=400, detail="entity, relation, and target_value required"
            )
        res = database.add_knowledge_relation_sync(
            uid, entity, relation, target, cat, tags
        )
        return {"status": "success", "result": res}


@router.post("/api/memory/delete")
async def delete_memory(request: Request, payload: dict[str, Any]):
    """Delete a memory fact by key (hanya admin)."""
    require_admin(request)
    uid = get_primary_user_id()
    key_topic = payload.get("key_topic")
    if not key_topic:
        raise HTTPException(status_code=400, detail="key_topic is required")

    db_path = os.path.join(REPO_ROOT, "agent_data.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "DELETE FROM knowledge_memory WHERE user_id = ? AND key_topic = ?",
            (uid, key_topic),
        )
        await db.commit()

    return {"status": "success", "message": f"Fakta '{key_topic}' berhasil dihapus."}


@router.get("/api/brain/export")
async def export_brain(request: Request):
    """Export complete Second Brain knowledge as Markdown and JSON (hanya admin)."""
    require_admin(request)
    uid = get_primary_user_id()
    memories = await database.get_all_memories(uid)
    kg = database.get_all_knowledge_graph_sync(uid)

    md_lines = [
        "# 🧠 ALFA SECOND BRAIN KNOWLEDGE EXPORT\n",
        f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n## 📝 Permanent Facts & Memories\n",
    ]
    for m in memories:
        md_lines.append(
            f"- **[{m['category'].upper()}] {m['key_topic']}**: {m['content']}"
        )

    md_lines.append("\n## 🕸️ Semantic Knowledge Graph\n")
    for k in kg:
        md_lines.append(
            f"- `{k['entity']}` ──*({k['relation']})*──> `{k['target_value']}` [{k['category']}]"
        )

    return {
        "status": "success",
        "markdown": "\n".join(md_lines),
        "json": {
            "user_id": uid,
            "exported_at": datetime.now().isoformat(),
            "memories": memories,
            "knowledge_graph": kg,
        },
    }


@router.post("/api/brain/vector/search")
async def api_vector_search(payload: dict[str, Any]):
    """Execute cosine semantic similarity search on permanent Vector Brain embeddings."""
    from alfa.memory import vector as vector_memory

    query = payload.get("query", "").strip()
    top_k = safe_int(payload.get("top_k", 5), 5, minimum=1, maximum=50)
    category = payload.get("category", "")
    uid = get_primary_user_id()

    if not query:
        return {"status": "error", "message": "Search query is required"}

    matches = vector_memory.semantic_search(
        user_id=uid, query=query, top_k=top_k, category=category or None
    )
    return {
        "status": "success",
        "query": query,
        "total_matches": len(matches),
        "matches": matches,
    }


@router.post("/api/brain/vector/ingest")
async def api_vector_ingest(request: Request, payload: dict[str, Any]):
    """Ingest, chunk, and embed a document or file into permanent Vector Brain (hanya admin)."""
    require_admin(request)
    from alfa.memory import vector as vector_memory

    title = payload.get("title", "").strip()
    content = payload.get("content", "").strip()
    category = payload.get("category", "general").strip()
    uid = get_primary_user_id()

    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")

    res = vector_memory.ingest_document(
        user_id=uid, title=title, content_or_path=content, category=category
    )
    return res


@router.get("/api/brain/vector/list")
async def api_vector_list():
    """List all ingested documents currently in Vector Brain."""
    from alfa.memory import vector as vector_memory

    uid = get_primary_user_id()
    docs = vector_memory.list_ingested_documents(user_id=uid)
    return {"status": "success", "total_documents": len(docs), "documents": docs}


@router.post("/api/brain/vector/delete")
async def api_vector_delete(request: Request, payload: dict[str, Any]):
    """Delete a document and its embedding chunks from Vector Brain (hanya admin)."""
    require_admin(request)
    from alfa.memory import vector as vector_memory

    doc_title = payload.get("doc_title", "").strip()
    uid = get_primary_user_id()
    if not doc_title:
        raise HTTPException(status_code=400, detail="doc_title is required")

    return vector_memory.delete_document(user_id=uid, doc_title=doc_title)


# ==================== GRAPHRAG KNOWLEDGE GRAPH ENDPOINTS ====================


@router.get("/api/brain/graph/overview")
async def api_graph_overview(doc_title: str = "", top_n: int = 10):
    """Ringkasan Knowledge Graph & Top Hubs."""
    from alfa.memory import graph_rag

    uid = get_primary_user_id()
    return graph_rag.graph_rag_get_overview(user_id=uid, doc_title=doc_title, top_n=top_n)


@router.get("/api/brain/graph/communities")
async def api_graph_communities(doc_title: str = ""):
    """Kluster komunitas entitas Knowledge Graph (Global Search)."""
    from alfa.memory import graph_rag

    uid = get_primary_user_id()
    return graph_rag.graph_rag_get_communities(user_id=uid, doc_title=doc_title)


@router.post("/api/brain/graph/path")
async def api_graph_path(payload: dict[str, Any]):
    """Pencarian rute relasi terpendek BFS antara dua entitas."""
    from alfa.memory import graph_rag

    uid = get_primary_user_id()
    ent_a = str(payload.get("entity_a", "")).strip()
    ent_b = str(payload.get("entity_b", "")).strip()
    max_depth = safe_int(payload.get("max_depth", 3), 3, minimum=1, maximum=6)
    if not ent_a or not ent_b:
        raise HTTPException(status_code=400, detail="entity_a dan entity_b wajib diisi.")

    return graph_rag.graph_rag_find_connection(
        user_id=uid, entity_a=ent_a, entity_b=ent_b, max_depth=max_depth
    )


@router.get("/api/brain/graph/elements")
async def api_graph_elements(doc_title: str = "", limit: int = 150):
    """Mengembalikan node & edge terstruktur untuk visualizer graf interaktif."""
    import sqlite3

    from alfa.memory import graph_rag
    from alfa.memory.vector import _resolve_db_path

    uid = get_primary_user_id()
    db_path = _resolve_db_path(None)
    graph_rag.init_graph_db(db_path)

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        doc_filter = ""
        params: list[Any] = [uid]
        if doc_title:
            doc_filter = "AND source_doc = ?"
            params.append(doc_title.strip())

        query = (
            "SELECT source_entity, relation, target_entity, source_doc, evidence "  # nosec B608
            "FROM graph_relations "
            "WHERE user_id = ? {df} "
            "LIMIT ?"
        ).replace("{df}", doc_filter)
        params.append(limit)

        rows = conn.execute(query, params).fetchall()  # nosec B608 — static clause with ? placeholders

        nodes_map: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        for idx, r in enumerate(rows):
            src = str(r["source_entity"])
            rel = str(r["relation"])
            tgt = str(r["target_entity"])
            doc = str(r["source_doc"])
            ev = str(r["evidence"])

            for n in (src, tgt):
                if n not in nodes_map:
                    nodes_map[n] = {"id": n, "label": n, "degree": 0, "docs": set()}
                nodes_map[n]["degree"] += 1
                nodes_map[n]["docs"].add(doc)

            edges.append({
                "id": f"e{idx}",
                "source": src,
                "target": tgt,
                "label": rel,
                "doc": doc,
                "evidence": ev,
            })

        nodes = [
            {
                "id": n["id"],
                "label": n["label"],
                "degree": n["degree"],
                "docs": list(n["docs"]),
            }
            for n in nodes_map.values()
        ]

        return {
            "status": "success",
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "nodes": nodes,
            "edges": edges,
        }
    finally:
        conn.close()


@router.post("/api/brain/graph/consolidate")
async def consolidate_graph_endpoint(payload: dict[str, Any] | None = None):
    """Menjalankan siklus konsolidasi memori pengetahuan (Sleep Cycle Consolidation)."""
    from alfa.memory import graph_rag

    body = payload or {}
    auto_alias = bool(body.get("auto_alias", True))
    recluster = bool(body.get("recluster", True))
    uid = get_primary_user_id()

    result = graph_rag.consolidate_memory_sleep_cycle(
        user_id=uid,
        auto_alias=auto_alias,
        recluster=recluster,
    )
    return result


@router.get("/api/brain/graph/export")
async def export_graph_endpoint(format: str = "jsonld"):
    """Mengekspor Knowledge Graph ke format JSON-LD, GraphML, atau Cypher."""
    from alfa.memory import graph_rag

    uid = get_primary_user_id()
    fmt = format.lower().strip()
    result = graph_rag.export_knowledge_graph(
        format_type=fmt,
        user_id=uid,
    )

    if fmt == "graphml":
        return Response(
            content=str(result),
            media_type="application/xml",
            headers={"Content-Disposition": "attachment; filename=knowledge_graph.graphml"},
        )
    if fmt == "cypher":
        return PlainTextResponse(
            content=str(result),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=knowledge_graph.cql"},
        )
    return {"status": "success", "format": "jsonld", "data": result}

