# Multi-stage build: dependencies are compiled/installed in a throwaway
# builder stage, and only the resulting site-packages + app code are copied
# into the slim final image, keeping it free of build toolchains.

FROM python:3.12-slim AS builder

WORKDIR /build

# Build tooling needed to compile any C-extension wheels (e.g. bcrypt) that
# don't ship a manylinux wheel for this platform; not present in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim AS final

# Run as a dedicated non-root user rather than the container default root.
RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder /install /usr/local

WORKDIR /app
COPY app ./app

# SQLite data directory: docker-compose mounts a named volume here so
# app.db persists across container restarts/recreations.
RUN mkdir -p /app/data && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live').read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
