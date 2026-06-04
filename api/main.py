"""FastAPI application — sf-agents Demo Day API.

Start with:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root (parent of this file's directory).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import benchmark, deal, health, primitives, recipes, runs, strategies, use_cases

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="sf-agents API",
    description="Hypoport Demo Day — Structured Finance Hackathon 2026",
    version="0.2.0",
)

# Development CORS: Angular dev server only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(recipes.router, prefix="/api", tags=["recipes"])
app.include_router(use_cases.router, prefix="/api", tags=["use-cases"])
app.include_router(primitives.router, prefix="/api", tags=["primitives"])
app.include_router(strategies.router, prefix="/api", tags=["strategies"])
app.include_router(benchmark.router, prefix="/api", tags=["benchmark"])
app.include_router(deal.router, prefix="/api", tags=["deal"])
app.include_router(runs.router, prefix="/api", tags=["runs"])
