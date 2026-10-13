# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System-level build deps (for psycopg2, PuLP/CBC, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    coinor-cbc \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    coinor-cbc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY backend/ ./backend/
COPY data/     ./data/

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
