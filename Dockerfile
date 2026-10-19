FROM python:3.11-slim

# Install system dependencies (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source, seeds, initial logs, and report directories
COPY app/ ./app/
COPY seeds/ ./seeds/
COPY reports/ ./reports/
COPY logs/ ./logs/

# Default environment configurations
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    CELESTO_NO_TELEMETRY=1

EXPOSE 8080

# Health check against /health endpoint
HEALTHCHECK --interval=5s --timeout=3s --retries=5 --start-period=5s \
    CMD curl -f http://localhost:8080/health || exit 1

# Start FastAPI control plane server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
