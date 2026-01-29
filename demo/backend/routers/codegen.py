from fastapi import APIRouter
from pydantic import BaseModel

from models.schemas import (
    GenerateRequest,
    GenerateResponse,
    GenerateMetadata,
    StageTiming,
    CompileResponse,
)
from services.engine import CodeGenerator, get_sempipes_config, is_sempipes_available
from services.compile_parse import extract_nodes_with_ranges

router = APIRouter(prefix="/api", tags=["codegen"])
generator = CodeGenerator()


class CompileRequest(BaseModel):
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
    """Return graph nodes with source ranges for editor decorations and code–graph sync."""
    nodes = extract_nodes_with_ranges(req.input_code)
    return CompileResponse(nodes=nodes)


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
