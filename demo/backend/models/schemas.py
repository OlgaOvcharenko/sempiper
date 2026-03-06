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
    sempipes_available: bool = False
    sempipes_llm: str | None = None


class GenerateResponse(BaseModel):
    generated_code: str
    language: str
    compilation_time_ms: float
    metadata: GenerateMetadata


class SourceRange(BaseModel):
    """1-based line and column for editor decorations and code–graph mapping."""

    start_line: int
    start_column: int
    end_line: int
    end_column: int


class CompileNode(BaseModel):
    id: str
    type: str  # "input" | "operator" | "pipeline"
    label: str
    source_range: SourceRange | None = None
    """True if this node is a sempipes semantic operator that can produce generated code."""
    is_sempipes_semantic: bool = False


class CompileEdge(BaseModel):
    """Edge for graph: source -> target (node ids)."""

    source: str
    target: str


class CompileResponse(BaseModel):
    nodes: list[CompileNode]
    edges: list[CompileEdge] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list, description="Graph validation errors if any")
    compile_timings_ms: dict[str, float] | None = Field(
        default=None,
        description="Timing breakdown (ms) when X-Compile-Timing: 1 header was sent and use_dynamic=True",
    )


