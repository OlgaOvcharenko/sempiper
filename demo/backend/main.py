"""Demo backend: load .env before any app code so sempipes/LiteLLM see API keys."""
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root and from demo/backend so API keys (e.g. OPENAI_API_KEY, GEMINI_*) are available.
# Sempipes also calls load_dotenv() on import but only from cwd; we load explicitly so repo-root .env works.
_repo_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_repo_root / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import codegen_router

app = FastAPI(title="VLDB Code Gen Demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(codegen_router)


@app.get("/")
def root():
    """Backend is API-only. Open the frontend URL for the demo UI."""
    return {
        "message": "Demo API. Open http://localhost:5173 for the demo UI.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
