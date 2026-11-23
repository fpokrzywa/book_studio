# Personal Book Studio: one image for the web process and the background worker.
# Built by deploy/scripts/install.sh and update.sh (docker compose -f deploy/compose.yaml build app).
# See docs/DEPLOYMENT.md. Nothing from .pbs-data, .env or any workspace is copied (see .dockerignore).

# ---------- 1. the browser UI (static files) ----------
FROM node:22-trixie-slim AS ui
WORKDIR /src
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/studio-ui/package.json apps/studio-ui/
RUN pnpm install --frozen-lockfile --filter studio-ui --ignore-scripts
COPY apps/studio-ui apps/studio-ui
RUN pnpm --filter studio-ui exec vite build

# ---------- 2. Core's Python environment ----------
FROM python:3.12-slim-trixie AS core
COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY apps/studio-core/pyproject.toml apps/studio-core/uv.lock apps/studio-core/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/studio-core/src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---------- 3. runtime ----------
FROM python:3.12-slim-trixie
# Optional tools (docs/DEPLOYMENT.md, "Optional tools"): eSpeak NG for local narration.
ARG WITH_ESPEAK=0
ARG PBS_REVISION=local
LABEL org.opencontainers.image.title="Personal Book Studio" \
      org.opencontainers.image.source="https://github.com/fpokrzywa/book_studio" \
      org.opencontainers.image.revision="${PBS_REVISION}"
RUN set -eux; \
    extra=""; [ "$WITH_ESPEAK" = "1" ] && extra="espeak-ng"; \
    apt-get update; \
    apt-get install -y --no-install-recommends tini fonts-dejavu-core $extra; \
    rm -rf /var/lib/apt/lists/*; \
    useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin pbs; \
    mkdir -p /data && chown pbs:pbs /data && chmod 700 /data
COPY --from=core /app/.venv /app/.venv
COPY --from=ui /src/apps/studio-ui/dist /app/ui
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PBS_ENV=prod \
    PBS_DEPLOYMENT=server \
    PBS_HOST=0.0.0.0 \
    PBS_PORT=8765 \
    PBS_WORKSPACE=/data \
    PBS_UI_DIST=/app/ui \
    PBS_LOG_CONSOLE=true \
    PBS_REVISION=${PBS_REVISION}
USER pbs
WORKDIR /app
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4)"]
ENTRYPOINT ["tini", "--", "python", "-m", "pbs_core"]
CMD ["serve"]
