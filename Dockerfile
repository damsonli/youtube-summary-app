# One image: the React UI is built with Node, then served by the FastAPI app.

# ---- 1. build the frontend ----------------------------------------------------
FROM node:26.13.0-alpine3.24 AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. python dependencies ---------------------------------------------------
FROM python:3.14.10-slim-trixie AS base
COPY --from=astral/uv:0.13.6 /uv /usr/local/bin/uv
# yt-dlp needs a JavaScript runtime to extract YouTube data
COPY --from=denoland/deno:bin-2.9.8 /deno /usr/local/bin/deno
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

# ---- 3. tests (docker build --target test .) ---------------------------------
FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY backend/ ./
RUN ruff check app tests && pytest -q

# ---- 4. runtime ---------------------------------------------------------------
FROM base AS runtime
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown app /app/data
COPY backend/app ./app
COPY --from=web /web/dist ./static
ENV DATA_DIR=/app/data STATIC_DIR=/app/static
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
