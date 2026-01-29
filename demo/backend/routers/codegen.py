from fastapi import APIRouter
from models.schemas import GenerateRequest, GenerateResponse, GenerateMetadata, StageTiming
from services.engine import CodeGenerator

router = APIRouter(prefix="/api", tags=["codegen"])
generator = CodeGenerator()


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
        ),
    )
