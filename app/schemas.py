"""Pydantic schemas and validation contracts for Celesto ResearchGuard."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


SANDBOX_NAME_REGEX = re.compile(r"^sbx-[a-z0-9]{8,}$")
ALLOWED_EXECUTION_TARGET = "celesto_sandbox"


class RunState(str, Enum):
    """Allowed states for runs in the ledger."""
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DELETED = "deleted"


class RunCreateRequest(BaseModel):
    """Request contract for POST /api/runs."""
    run_id: str = Field(..., min_length=1, description="Unique identifier for this run")
    sandbox_name: str = Field(..., description="Unique sandbox computer name (must match ^sbx-[a-z0-9]{8,}$)")
    problem_id: str = Field(..., min_length=1, description="Associated problem or research task ID")
    state: RunState = Field(..., description="Run lifecycle state")
    execution_target: str = Field(..., description="Execution zone target (must equal celesto_sandbox)")

    @field_validator("sandbox_name")
    @classmethod
    def validate_sandbox_name(cls, v: str) -> str:
        if not SANDBOX_NAME_REGEX.match(v):
            raise ValueError(
                f"sandbox_name '{v}' is invalid; must match pattern '^sbx-[a-z0-9]{{8,}}$'"
            )
        return v

    @field_validator("execution_target")
    @classmethod
    def validate_execution_target(cls, v: str) -> str:
        if v != ALLOWED_EXECUTION_TARGET:
            raise ValueError(
                f"execution_target '{v}' is prohibited; must equal '{ALLOWED_EXECUTION_TARGET}'"
            )
        return v


class RunRecordResponse(BaseModel):
    """Ledger record representation returned by GET and POST /api/runs."""
    run_id: str
    sandbox_name: str
    problem_id: str
    state: str
    execution_target: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True
    }


class ResearchTaskRequest(BaseModel):
    """Trigger contract for starting a research workflow."""
    topic: str = Field(..., min_length=3, description="Research topic or query")
    permitted_urls: List[str] = Field(
        default_factory=list,
        description="Strictly bounded list of public URLs the sandbox browser is permitted to access"
    )
    sandbox_name: Optional[str] = Field(
        None,
        description="Optional custom sandbox name (must match regex if provided)"
    )

    @field_validator("sandbox_name")
    @classmethod
    def validate_optional_sandbox_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not SANDBOX_NAME_REGEX.match(v):
            raise ValueError(
                f"sandbox_name '{v}' is invalid; must match pattern '^sbx-[a-z0-9]{{8,}}$'"
            )
        return v


class ResearchTaskResponse(BaseModel):
    """Response contract when starting or concluding a research run."""
    run_id: str
    sandbox_name: str
    state: str
    artifact_path: Optional[str] = None
    boot_to_ready_s: Optional[float] = None
    wall_clock_s: Optional[float] = None
    findings_count: int = 0
    message: str
