-- Schema and Seed initialization for Celesto ResearchGuard Run Ledger
-- Idempotent initialization script for PostgreSQL container

CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR(128) PRIMARY KEY,
    sandbox_name VARCHAR(128) NOT NULL,
    problem_id VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    execution_target VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_run_state CHECK (state IN ('created', 'ready', 'running', 'succeeded', 'failed', 'deleted')),
    CONSTRAINT check_sandbox_name CHECK (sandbox_name ~ '^sbx-[a-z0-9]{8,}$'),
    CONSTRAINT check_execution_target CHECK (execution_target = 'celesto_sandbox')
);

-- Index for querying by state and sandbox_name
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs (state);
CREATE INDEX IF NOT EXISTS idx_runs_sandbox_name ON runs (sandbox_name);

-- Idempotent seed insertion of initial demo record sbx-seeddemo1
INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'problem-seed-init', 'deleted', 'celesto_sandbox')
ON CONFLICT (run_id) DO UPDATE 
SET sandbox_name = EXCLUDED.sandbox_name,
    problem_id = EXCLUDED.problem_id,
    state = EXCLUDED.state,
    execution_target = EXCLUDED.execution_target,
    updated_at = CURRENT_TIMESTAMP;
