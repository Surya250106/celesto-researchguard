"""Trusted Control Plane Database Configuration and Run Ledger persistence."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Generator, List, Optional

from sqlalchemy import Column, DateTime, String, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker, Session

logger = logging.getLogger(__name__)

Base = declarative_base()


class RunModel(Base):
    """SQLAlchemy model representing the Run Ledger in PostgreSQL."""
    __tablename__ = "runs"

    run_id = Column(String(128), primary_key=True, index=True)
    sandbox_name = Column(String(128), nullable=False, index=True)
    problem_id = Column(String(128), nullable=False)
    state = Column(String(32), nullable=False, index=True)
    execution_target = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "sandbox_name": self.sandbox_name,
            "problem_id": self.problem_id,
            "state": self.state,
            "execution_target": self.execution_target,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def get_engine():
    """Create and return a connected SQLAlchemy engine with fast fallback to SQLite for offline testing."""
    configured_url = os.environ.get("DATABASE_URL")
    if configured_url:
        connect_args = {}
        if "sqlite" in configured_url:
            connect_args = {"check_same_thread": False}
        elif "postgres" in configured_url:
            connect_args = {"connect_timeout": 2}
        try:
            eng = create_engine(configured_url, connect_args=connect_args, pool_pre_ping=True)
            with eng.connect() as conn:
                pass
            return eng
        except Exception as e:
            logger.warning("Configured database %s unreachable (%s); using SQLite fallback", configured_url, e)

    # Check local PostgreSQL with 1-second timeout
    try:
        default_pg = "postgresql+psycopg://postgres:postgres@localhost:5432/researchguard"
        eng = create_engine(default_pg, connect_args={"connect_timeout": 1}, pool_pre_ping=True)
        with eng.connect() as conn:
            pass
        return eng
    except Exception:
        # Graceful SQLite fallback for offline development & tests
        fallback_url = "sqlite:///./fallback_test_ledger.db"
        return create_engine(fallback_url, connect_args={"check_same_thread": False})


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(engine_override=None) -> None:
    """Initialize database tables and ensure idempotent seed demo record exists."""
    target_engine = engine_override or engine
    Base.metadata.create_all(bind=target_engine)

    # Ensure sbx-seeddemo1 exists as required by hackathon spec
    db: Session = SessionLocal()
    try:
        seed = db.execute(select(RunModel).where(RunModel.run_id == "run-seeddemo1")).scalar_one_or_none()
        if not seed:
            seed = RunModel(
                run_id="run-seeddemo1",
                sandbox_name="sbx-seeddemo1",
                problem_id="problem-seed-init",
                state="deleted",
                execution_target="celesto_sandbox",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(seed)
            db.commit()
    except Exception as e:
        logger.warning("Failed to seed initial record: %s", e)
        db.rollback()
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def list_runs(db: Session) -> List[RunModel]:
    """Retrieve all run records from the ledger."""
    stmt = select(RunModel).order_by(RunModel.created_at.desc())
    return list(db.scalars(stmt).all())


def get_run(db: Session, run_id: str) -> Optional[RunModel]:
    """Retrieve a single run record by ID."""
    stmt = select(RunModel).where(RunModel.run_id == run_id)
    return db.execute(stmt).scalar_one_or_none()


def save_run(
    db: Session,
    run_id: str,
    sandbox_name: str,
    problem_id: str,
    state: str,
    execution_target: str
) -> RunModel:
    """Idempotently insert or update a run ledger record."""
    existing = get_run(db, run_id)
    now = datetime.now(timezone.utc)
    if existing:
        existing.sandbox_name = sandbox_name
        existing.problem_id = problem_id
        existing.state = state
        existing.execution_target = execution_target
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return existing
    else:
        new_record = RunModel(
            run_id=run_id,
            sandbox_name=sandbox_name,
            problem_id=problem_id,
            state=state,
            execution_target=execution_target,
            created_at=now,
            updated_at=now,
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        return new_record
