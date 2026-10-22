# ==============================================================================
# Scholarship Star Production Dockerfile – Optimized for Google Cloud Run (Scale-to-Zero)
# ==============================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final minimal runtime image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    PATH=/root/.local/bin:$PATH

WORKDIR /app

# Copy installed python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application source code
COPY . .

# Create directory for runtime logs and cache
RUN mkdir -p /app/runs /app/.cache

EXPOSE 8080

# Cloud Run default entrypoint with graceful shutdown handling
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --timeout-keep-alive 65
