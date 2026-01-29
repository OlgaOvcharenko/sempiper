from pydantic import BaseModel, Field


class GenerateOptions(BaseModel):
    optimization_level: int = Field(default=2, ge=0, le=3)
    target: str = Field(default="cpp", pattern="^(cpp|rust|llvm)$")


class GenerateRequest(BaseModel):
    input_code: str
    options: GenerateOptions | None = None


class StageTiming(BaseModel):
    name: str
    time_ms: float


class GenerateMetadata(BaseModel):
    optimizations_applied: list[str] = Field(default_factory=list)
    ir_size_bytes: int = 0
    stages: list[StageTiming] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    generated_code: str
    language: str
    compilation_time_ms: float
    metadata: GenerateMetadata
