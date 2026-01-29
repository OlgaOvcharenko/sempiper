from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from models.schemas import (
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


@router.post("/compile", response_model=CompileResponse)
def compile_pipeline(req: CompileRequest) -> CompileResponse:
    """Return graph nodes and edges with source ranges for editor decorations and code–graph sync."""
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
