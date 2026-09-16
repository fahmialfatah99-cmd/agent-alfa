import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite
import psutil
from dotenv import dotenv_values
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from alfa.core import database
from alfa import tools
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, logger, safe_int

router = APIRouter()

# ==================== PIPELINES WORKFLOW ENGINE ====================

@router.get("/api/pipelines")
async def list_pipelines_endpoint():
    """Daftar pipeline workflow yang tersedia."""
    import pipelines as pl
    return {"status": "success", "pipelines": pl.list_pipelines()}


@router.get("/api/pipelines/{pid}")
async def get_pipeline_endpoint(pid: str):
    import pipelines as pl
    try:
        return {"status": "success", "pipeline": pl.load_pipeline(pid)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Pipeline tidak ditemukan.")


@router.post("/api/pipelines/{pid}/run")
async def run_pipeline_endpoint(pid: str, request: Request):
    """Jalankan pipeline; body JSON opsional: overrides variabel {"vars": {...}}."""
    import pipelines as pl
    try:
        overrides = {}
        try:
            body = await request.json()
            if isinstance(body, dict):
                overrides = body.get("vars") or {}
        except Exception:
            pass
        result = await asyncio.wait_for(pl.run_pipeline(pid, overrides), timeout=600)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Pipeline tidak ditemukan.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/pipelines/{pid}")
async def save_pipeline_endpoint(pid: str, request: Request):
    """Simpan/overwrite definisi pipeline dari Canvas Studio."""
    import pipelines as pl
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body harus JSON valid.")
    if not isinstance(data, dict) or not data.get("steps"):
        raise HTTPException(status_code=400, detail="Pipeline wajib punya 'steps'.")
    data["id"] = pid
    try:
        path = pl.save_pipeline(data)
        return {"status": "success", "file": os.path.basename(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/pipelines/{pid}/webhook")
async def pipeline_webhook_endpoint(pid: str, request: Request):
    """Trigger webhook ala n8n: POST di sini menjalankan pipeline."""
    import pipelines as pl
    try:
        data = pl.load_pipeline(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Pipeline tidak ditemukan.")
    secret = ((data.get("trigger") or {}).get("secret") or "").strip()
    if secret:
        provided = (request.headers.get("X-Webhook-Key") or
                    request.query_params.get("key") or "")
        if provided != secret:
            raise HTTPException(status_code=401, detail="Webhook key salah.")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    overrides = {"payload": payload if isinstance(payload, dict) else {"raw": payload}}
    result = await asyncio.wait_for(pl.run_pipeline(pid, overrides), timeout=600)
    return {k: result[k] for k in ("pipeline", "status", "duration_ms", "outputs") if k in result}


@router.get("/api/pipelines/{pid}/runs")
async def pipeline_runs_endpoint(pid: str, limit: int = 10):
    """Riwayat eksekusi pipeline terakhir."""
    import pipelines as pl
    return {"status": "success", "pid": pid, "runs": pl.list_runs(pid, limit)}


@router.post("/api/pipelines/{pid}/enable")
async def pipeline_trigger_toggle_endpoint(pid: str, request: Request):
    """Aktif/matikan trigger jadwal: body {"enabled": true/false}."""
    import pipelines as pl
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
        raise HTTPException(status_code=404, detail="Pipeline tidak ditemukan.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        "knowledge_graph": kg
    }


@router.post("/api/memory/add")
async def add_memory(payload: Dict[str, Any]):
    """Add a new memory fact or knowledge graph relation."""
    uid = get_primary_user_id()
    m_type = payload.get("type", "fact")

    if m_type == "fact":
        key = payload.get("key_topic")
        content = payload.get("content")
        cat = payload.get("category", "general")
        if not key or not content:
            raise HTTPException(status_code=400, detail="key_topic and content required")
        res = database.save_memory_fact_sync(uid, key, content, cat)
        return {"status": "success", "result": res}
    else:
        entity = payload.get("entity")
        relation = payload.get("relation")
        target = payload.get("target_value")
        cat = payload.get("category", "general")
        tags = payload.get("tags", "")
        if not entity or not relation or not target:
            raise HTTPException(status_code=400, detail="entity, relation, and target_value required")
        res = database.add_knowledge_relation_sync(uid, entity, relation, target, cat, tags)
        return {"status": "success", "result": res}


@router.post("/api/memory/delete")
async def delete_memory(payload: Dict[str, Any]):
    """Delete a memory fact by key."""
    uid = get_primary_user_id()
    key_topic = payload.get("key_topic")
    if not key_topic:
        raise HTTPException(status_code=400, detail="key_topic is required")

    db_path = os.path.join(REPO_ROOT, "agent_data.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM knowledge_memory WHERE user_id = ? AND key_topic = ?", (uid, key_topic))
        await db.commit()

    return {"status": "success", "message": f"Fakta '{key_topic}' berhasil dihapus."}


@router.get("/api/brain/export")
async def export_brain():
    """Export complete Second Brain knowledge as Markdown and JSON."""
    uid = get_primary_user_id()
    memories = await database.get_all_memories(uid)
    kg = database.get_all_knowledge_graph_sync(uid)

    md_lines = ["# 🧠 ALFA SECOND BRAIN KNOWLEDGE EXPORT\n", f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n## 📝 Permanent Facts & Memories\n"]
    for m in memories:
        md_lines.append(f"- **[{m['category'].upper()}] {m['key_topic']}**: {m['content']}")

    md_lines.append("\n## 🕸️ Semantic Knowledge Graph\n")
    for k in kg:
        md_lines.append(f"- `{k['entity']}` ──*({k['relation']})*──> `{k['target_value']}` [{k['category']}]")

    return {
        "status": "success",
        "markdown": "\n".join(md_lines),
        "json": {
            "user_id": uid,
            "exported_at": datetime.now().isoformat(),
            "memories": memories,
            "knowledge_graph": kg
        }
    }


@router.post("/api/brain/vector/search")
async def api_vector_search(payload: Dict[str, Any]):
    """Execute cosine semantic similarity search on permanent Vector Brain embeddings."""
    import vector_memory
    query = payload.get("query", "").strip()
    top_k = safe_int(payload.get("top_k", 5), 5, minimum=1, maximum=50)
    category = payload.get("category", "")
    uid = get_primary_user_id()

    if not query:
        return {"status": "error", "message": "Search query is required"}

    matches = vector_memory.semantic_search(user_id=uid, query=query, top_k=top_k, category=category or None)
    return {
        "status": "success",
        "query": query,
        "total_matches": len(matches),
        "matches": matches
    }


@router.post("/api/brain/vector/ingest")
async def api_vector_ingest(payload: Dict[str, Any]):
    """Ingest, chunk, and embed a document or file into permanent Vector Brain."""
    import vector_memory
    title = payload.get("title", "").strip()
    content = payload.get("content", "").strip()
    category = payload.get("category", "general").strip()
    uid = get_primary_user_id()

    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")

    res = vector_memory.ingest_document(user_id=uid, title=title, content_or_path=content, category=category)
    return res


@router.get("/api/brain/vector/list")
async def api_vector_list():
    """List all ingested documents currently in Vector Brain."""
    import vector_memory
    uid = get_primary_user_id()
    docs = vector_memory.list_ingested_documents(user_id=uid)
    return {
        "status": "success",
        "total_documents": len(docs),
        "documents": docs
    }


@router.post("/api/brain/vector/delete")
async def api_vector_delete(payload: Dict[str, Any]):
    """Delete a document and its embedding chunks from Vector Brain."""
    import vector_memory
    doc_title = payload.get("doc_title", "").strip()
    uid = get_primary_user_id()
    if not doc_title:
        raise HTTPException(status_code=400, detail="doc_title is required")

    return vector_memory.delete_document(user_id=uid, doc_title=doc_title)


