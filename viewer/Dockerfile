# miniview's service (ADR-0005, RFC-0009 "Running in Docker", ADR-0012): the API, the live streams and the two
# pages. The runs and scenes are mounted READ ONLY at /data/runs and /data/scenes; the host's state folder (the one
# index) is mounted at /index. Pictures for the agent (Chromium) stay outside the image.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH MINIVIEW_DATA=/data MINIVIEW_INDEX=/index/index.sqlite PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY web ./web
RUN uv sync --frozen --no-dev
RUN mkdir -p /index /data

EXPOSE 8070
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8070/api/v1/health', timeout=2)"
CMD ["miniview", "--data", "/data", "serve", "--host", "0.0.0.0", "--port", "8070"]
