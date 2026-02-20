import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from models.schemas import (
    CompileResponse,
    GenerateMetadata,
    GenerateRequest,
    GenerateResponse,
    StageTiming,
)
from pydantic import BaseModel, Field
from services.cache import CacheFormat, cache_service, make_cache_key
from services.cache.utils import _normalize_script
from services.graph_api import compile_script_to_graph, compile_script_to_graph_dynamic, save_svg_to_cache_async
from services.engine import CodeGenerator, get_sempipes_config, is_sempipes_available
from services.execute_stream import stream_execute_events

router = APIRouter(prefix="/api", tags=["codegen"])
generator = CodeGenerator()

# Pipeline scripts live in pipeline_scripts/ at repository root (parent of demo/).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PIPELINE_SCRIPTS_DIR = _REPO_ROOT / "pipeline_scripts"


def _get_pipeline_scripts_dir() -> Path:
    """Return pipeline_scripts directory; try repo root first, then cwd."""
    if (_PIPELINE_SCRIPTS_DIR / "manifest.json").is_file():
        return _PIPELINE_SCRIPTS_DIR
    cwd = Path.cwd()
    for base in (cwd, cwd.parent):
        candidate = base / "pipeline_scripts" / "manifest.json"
        if candidate.is_file():
            return candidate.parent
    return _PIPELINE_SCRIPTS_DIR


def _load_manifest() -> list[dict]:
    scripts_dir = _get_pipeline_scripts_dir()
    manifest_path = scripts_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


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
    scripts_dir = _get_pipeline_scripts_dir()
    path = scripts_dir / entry["file"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Script file not found: {entry['file']}")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return {"id": entry["id"], "label": entry["label"], "content": content}


class CompileRequest(BaseModel):
    input_code: str
    use_dynamic: bool = True  # Use dynamic skrub graph for accurate full DAG with all operations
    script_id: str | None = None  # Script id for SVG caching (simple, medium, full)
    llm_name: str | None = None  # LLM model name for caching
    temperature: float | None = None  # LLM temperature for caching (0-2)
    use_cache: bool = True  # Whether to use caching


class ExecuteRequest(BaseModel):
    input_code: str
    script_id: str | None = None  # Loaded script id (simple, medium, full); used to save SVG by name
    llm_name: str | None = None  # LLM model name for caching
    temperature: float | None = None  # LLM temperature for caching (0-2)
    use_cache: bool = True  # Whether to use caching


class UpdateConfigRequest(BaseModel):
    llm_name: str
    temperature: float = Field(ge=0.0, le=2.0, description="Temperature for LLM (0-2)")


@router.post("/update-config")
def update_sempipes_config(req: UpdateConfigRequest) -> dict:
    """Update sempipes config with LLM name and temperature."""
    try:
        import sempipes
        sempipes.update_config(
            llm_for_code_generation=sempipes.LLM(
                name=req.llm_name,
                parameters={"temperature": req.temperature}
            )
        )
        return {"status": "ok", "llm_name": req.llm_name, "temperature": req.temperature}
    except ImportError:
        raise HTTPException(status_code=500, detail="sempipes not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sempipes-info")
def sempipes_info() -> dict:
    """Return whether sempipes is available in this environment and its config (if any)."""
    return {
        "available": is_sempipes_available(),
        "config": get_sempipes_config(),
    }


def _compile_timing_enabled(request: Request) -> bool:
    """True when compile timing should be collected (X-Compile-Timing: 1 or DEBUG set)."""
    return request.headers.get("X-Compile-Timing") == "1" or os.environ.get("DEBUG")


def _can_use_cache(req_use_cache: bool, llm_name: str | None, temperature: float | None) -> bool:
    """Check if caching can be used (requires all cache key components)."""
    return req_use_cache and llm_name is not None and temperature is not None


@router.post("/compile", response_model=CompileResponse)
def compile_pipeline(req: CompileRequest, request: Request) -> CompileResponse:
    """
    Return graph nodes and edges with source ranges.

    By default uses dynamic extraction (use_dynamic=True) for the real skrub graph.
    Dynamic compile runs the pipeline script (data load, subsample, etc.), so it can
    be slow for large scripts; send use_dynamic=false for fast static parsing when
    you only need the graph structure from code.
    Send X-Compile-Timing: 1 (or set DEBUG) to log compile timing breakdown.
    If script_id is provided, saves the native skrub SVG asynchronously.
    Caching: If llm_name and temperature are provided, results are cached.
    """
    # Check cache first
    cache_key = None
    if _can_use_cache(req.use_cache, req.llm_name, req.temperature):
        cache_key = make_cache_key(req.input_code, req.temperature, req.llm_name)
        cached = cache_service.get(cache_key, "compile")
        if cached:
            return CompileResponse(**cached)

    timings: dict[str, float] | None = (
        {} if (_compile_timing_enabled(request) and req.use_dynamic) else None
    )
    svg_out: list[str] = []
    if req.use_dynamic:
        result = compile_script_to_graph_dynamic(req.input_code, timings_out=timings, svg_out=svg_out)
        # Save SVG to cache asynchronously if cache_key is available
        if cache_key and svg_out:
            save_svg_to_cache_async(svg_out[0], cache_key)
    else:
        result = compile_script_to_graph(req.input_code)
    if timings and len(timings) > 0:
        logging.getLogger(__name__).info("compile_timings_ms: %s", timings)

    response = CompileResponse(
        nodes=result.nodes,
        edges=result.edges,
        validation_errors=result.validation_errors,
        compile_timings_ms=timings if timings else None,
    )

    # Store in cache with metadata (normalized script, model, temperature)
    if cache_key:
        metadata = {
            "script": _normalize_script(req.input_code),  # Store normalized version
            "llm_name": req.llm_name,
            "temperature": req.temperature,
            "script_id": req.script_id,
            "use_dynamic": req.use_dynamic,
        }
        cache_service.set(cache_key, "compile", response.model_dump(), metadata=metadata)

    return response


def _replay_cached_events(cached_events: list[dict]):
    """Generator that replays cached SSE events."""
    for event in cached_events:
        yield f"data: {json.dumps(event)}\n\n"


def _stream_and_cache_events(
    input_code: str,
    script_id: str | None,
    cache_key: str | None,
    llm_name: str | None,
    temperature: float | None,
):
    """Stream execute events while collecting them for caching."""
    collected_events: list[dict] = []

    for event_bytes in stream_execute_events(
        input_code,
        script_id=script_id,
        llm_name=llm_name,
        temperature=temperature,
        cache_key=cache_key,
    ):
        # Parse event to collect for caching
        # stream_execute_events yields bytes
        event_str = event_bytes.decode("utf-8") if isinstance(event_bytes, bytes) else event_bytes
        if event_str.startswith("data: "):
            try:
                # Remove "data: " prefix and trailing newlines
                json_str = event_str[6:].rstrip("\n")
                event_data = json.loads(json_str)
                collected_events.append(event_data)
            except json.JSONDecodeError:
                pass

        yield event_bytes

    # Store in cache after streaming completes with metadata (normalized script)
    if cache_key and collected_events:
        metadata = {
            "script": _normalize_script(input_code),  # Store normalized version
            "llm_name": llm_name,
            "temperature": temperature,
            "script_id": script_id,
        }
        cache_service.set(cache_key, "execute", {"events": collected_events}, metadata=metadata)


@router.post("/execute")
def execute_pipeline(req: ExecuteRequest):
    """
    Execute the pipeline and stream SSE events: terminal (line) and node_code (node_id, generated_code).
    Frontend shows live terminal output and live-updating code blocks per node.
    Caching: If llm_name and temperature are provided, results are cached.
    """
    # Check cache first
    cache_key = None
    if _can_use_cache(req.use_cache, req.llm_name, req.temperature):
        cache_key = make_cache_key(req.input_code, req.temperature, req.llm_name)
        cached = cache_service.get(cache_key, "execute")
        if cached and "events" in cached:
            return StreamingResponse(
                _replay_cached_events(cached["events"]),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    return StreamingResponse(
        _stream_and_cache_events(
            req.input_code,
            script_id=req.script_id,
            cache_key=cache_key,
            llm_name=req.llm_name,
            temperature=req.temperature,
        ),
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


class CacheSvgRequest(BaseModel):
    """Request to retrieve cached SVG."""
    input_code: str
    llm_name: str
    temperature: float


@router.post("/cache/svg")
def get_cached_svg(req: CacheSvgRequest):
    """
    Retrieve cached SVG for a given configuration.

    Returns the SVG string if cached, or 404 if not found.
    """
    cache_key = make_cache_key(req.input_code, req.temperature, req.llm_name)
    cached = cache_service.get(cache_key, "svg", format=CacheFormat.SVG)
    if cached:
        return {"svg": cached, "cache_key": cache_key}
    raise HTTPException(status_code=404, detail="SVG not found in cache")


@router.delete("/cache")
def clear_cache():
    """Clear all cached data (compile, execute, svg)."""
    cache_service.clear()
    return {"status": "cleared"}
