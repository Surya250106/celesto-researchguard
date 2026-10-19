"""FastAPI Trusted Control Plane for Celesto ResearchGuard.

Provides health checks, run ledger CRUD endpoints, report serving,
and research task orchestration.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import RunModel, get_db, init_db, list_runs, save_run
from app.agent import ResearchAgent
from app.sandbox import CelestoCredentialsMissingError
from app.schemas import (
    ResearchTaskRequest,
    ResearchTaskResponse,
    RunCreateRequest,
    RunRecordResponse,
)

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("celesto_control_plane")

REPORTS_DIR = Path("reports")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and shutdown hooks."""
    logger.info("Initializing database and ensuring seed data...")
    init_db()
    logger.info("Celesto ResearchGuard Control Plane initialized.")
    yield
    logger.info("Shutting down Celesto ResearchGuard Control Plane.")


app = FastAPI(
    title="Celesto ResearchGuard Control Plane",
    description="Trusted control plane and audit ledger for bounded sandboxed AI research agents.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Map request validation errors to HTTP 400 Bad Request as required by the specification."""
    error_msgs = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        error_msgs.append(f"{loc}: {msg}")
    logger.warning("Request validation failed: %s", error_msgs)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": error_msgs, "error": "Validation error"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Map value errors (such as invalid regex or execution target) to HTTP 400."""
    logger.warning("Validation ValueError: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error": "Bad Request"},
    )


@app.exception_handler(CelestoCredentialsMissingError)
async def credentials_missing_handler(request: Request, exc: CelestoCredentialsMissingError):
    """Fail clearly when a live Celesto run is requested without required credentials."""
    logger.error("Missing Celesto credentials: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error": "CelestoCredentialsMissing"},
    )


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check() -> dict:
    """Standard health check endpoint required by hackathon specification."""
    return {"status": "ok"}


@app.get("/api/runs", response_model=List[RunRecordResponse], status_code=status.HTTP_200_OK)
def get_runs(db: Session = Depends(get_db)):
    """Retrieve all run ledger records."""
    records = list_runs(db)
    return records


@app.post("/api/runs", response_model=RunRecordResponse, status_code=status.HTTP_201_CREATED)
def create_run_record(payload: RunCreateRequest, db: Session = Depends(get_db)):
    """Store or update a run record in the ledger."""
    record = save_run(
        db=db,
        run_id=payload.run_id,
        sandbox_name=payload.sandbox_name,
        problem_id=payload.problem_id,
        state=payload.state.value,
        execution_target=payload.execution_target,
    )
    return record


@app.post("/api/research", response_model=ResearchTaskResponse, status_code=status.HTTP_200_OK)
def trigger_research(payload: ResearchTaskRequest, db: Session = Depends(get_db)):
    """Execute a 10-step bounded research workflow inside a Celesto sandbox."""
    agent = ResearchAgent(
        topic=payload.topic,
        permitted_urls=payload.permitted_urls,
        sandbox_name=payload.sandbox_name,
        db_session=db,
    )
    result = agent.execute_with_recovery()
    return ResearchTaskResponse(
        run_id=result["run_id"],
        sandbox_name=result["sandbox_name"],
        state=result["state"],
        artifact_path="/tmp/research_report.md",
        boot_to_ready_s=result.get("boot_to_ready_s"),
        wall_clock_s=result.get("wall_clock_s"),
        findings_count=result.get("findings_count", 0),
        message="Research task concluded successfully within sandbox containment.",
    )


@app.get("/api/reports/{report_name}")
def get_report(report_name: str):
    """Serve existing report files from the reports directory."""
    clean_name = os.path.basename(report_name)
    file_path = REPORTS_DIR / clean_name
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report file '{clean_name}' not found",
        )
    if clean_name.endswith(".json"):
        return FileResponse(file_path, media_type="application/json")
    if clean_name.endswith(".md"):
        return FileResponse(file_path, media_type="text/markdown")
    if clean_name.endswith(".jsonl"):
        return FileResponse(file_path, media_type="application/x-ndjson")
    return FileResponse(file_path, media_type="application/octet-stream")
