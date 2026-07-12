# BAS Assistant - Docker Image
# Multi-stage build for smaller production image

# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency files
COPY pyproject.toml README.md ./

# Install dependencies
RUN pip install --no-cache-dir -e .

# Runtime stage
FROM python:3.12-slim AS runtime

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY src/ ./src/
COPY ui/ ./ui/
COPY examples/ ./examples/
COPY docs/ ./docs/
COPY scripts/ ./scripts/
COPY docker-entrypoint.sh ./
COPY pyproject.toml ./
COPY README.md ./

# Create data directories with correct ownership
RUN mkdir -p /app/data /app/ui/output/projects && \
    chown -R appuser:appuser /app && \
    chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONPATH=/app \
    BAS_DATA_DIR=/app/data \
    BAS_OUTPUT_DIR=/app/ui/output \
    PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# Entrypoint
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Run the application
CMD ["uvicorn", "ui.api.main:app", "--host", "0.0.0.0", "--port", "8000"]