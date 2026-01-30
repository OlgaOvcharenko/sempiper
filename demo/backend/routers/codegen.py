import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from models.schemas import (
    CompileEdge,
    CompileNode,
    CompileResponse,
    GenerateMetadata,
    GenerateRequest,
    GenerateResponse,
    StageTiming,
)
from pydantic import BaseModel
from services.compile_parse import extract_nodes_with_ranges
from services.engine import CodeGenerator, get_sempipes_config, is_sempipes_available
from services.execute_stream import stream_execute_events

router = APIRouter(prefix="/api", tags=["codegen"])
generator = CodeGenerator()

# Pipeline scripts live in pipeline_scripts/ at repository root (parent of demo/).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PIPELINE_SCRIPTS_DIR = _REPO_ROOT / "pipeline_scripts"


def _load_manifest() -> list[dict]:
    manifest_path = _PIPELINE_SCRIPTS_DIR / "manifest.json"
    if not manifest_path.is_file():
        return []
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


@router.get("/scripts")
def list_scripts() -> dict:
    """Return list of pipeline scripts (id, label) from pipeline_scripts/manifest.json."""
    manifest = _load_manifest()
    return {"scripts": [{"id": e["id"], "label": e["label"]} for e in manifest]}


@router.get("/scripts/{name}")
def get_script_content(name: str) -> dict:
    """Return the content of a pipeline script by id (from pipeline_scripts/)."""
    manifest = _load_manifest()
    entry = next((e for e in manifest if e["id"] == name), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Script not found: {name}")
    path = _PIPELINE_SCRIPTS_DIR / entry["file"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Script file not found: {entry['file']}")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return {"id": entry["id"], "label": entry["label"], "content": content}


class CompileRequest(BaseModel):
    input_code: str


class ExecuteRequest(BaseModel):
    input_code: str


@router.get("/sempipes-info")
def sempipes_info() -> dict:
    """Return whether sempipes is available in this environment and its config (if any)."""
    return {
        "available": is_sempipes_available(),
        "config": get_sempipes_config(),
    }


def _fork_join_fixture() -> CompileResponse:
    """Fixture graph: A (input) forks to B and C, which join at D."""
    nodes = [
        CompileNode(id="A", type="input", label="as_X", source_range=None),
        CompileNode(id="B", type="operator", label="sem_fillna", source_range=None),
        CompileNode(id="C", type="operator", label="sem_gen_features", source_range=None),
        CompileNode(id="D", type="operator", label="skb.apply", source_range=None),
    ]
    edges = [
        CompileEdge(source="A", target="B"),
        CompileEdge(source="A", target="C"),
        CompileEdge(source="B", target="D"),
        CompileEdge(source="C", target="D"),
    ]
    return CompileResponse(nodes=nodes, edges=edges)


@router.post("/compile", response_model=CompileResponse)
def compile_pipeline(req: CompileRequest) -> CompileResponse:
    """Return graph nodes and edges with source ranges for editor decorations and code–graph sync."""
    if "fork-join" in req.input_code:
        return _fork_join_fixture()
    nodes, edges = extract_nodes_with_ranges(req.input_code)
    return CompileResponse(nodes=nodes, edges=edges)


@router.post("/execute")
def execute_pipeline(req: ExecuteRequest):
    """
    Execute the pipeline and stream SSE events: terminal (line) and node_code (node_id, generated_code).
    Frontend shows live terminal output and live-updating code blocks per node.
    """
    return StreamingResponse(
        stream_execute_events(req.input_code),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    opts = req.options.model_dump() if req.options else None
    result = generator.generate(req.input_code, opts)
    meta = result["metadata"]
    return GenerateResponse(
        generated_code=result["generated_code"],
        language=result["language"],
        compilation_time_ms=result["compilation_time_ms"],
        metadata=GenerateMetadata(
            optimizations_applied=meta["optimizations_applied"],
            ir_size_bytes=meta["ir_size_bytes"],
            stages=[StageTiming(**s) for s in meta["stages"]],
            sempipes_available=meta.get("sempipes_available", False),
            sempipes_llm=meta.get("sempipes_llm"),
        ),
    )
