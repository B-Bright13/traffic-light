# Multi-stage build — AMD64, optimised for AWS Fargate
FROM --platform=linux/amd64 python:3.13-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Final stage ──────────────────────────────────────────────────────────────
FROM --platform=linux/amd64 python:3.13-slim

# Patch OS packages
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /venv /venv
COPY app.py .
COPY templates/ templates/

ENV PATH=/venv/bin:$PATH
ENV PORT=5000
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"

CMD ["python", "app.py"]
