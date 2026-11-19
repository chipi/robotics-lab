# miniview's service (ADR-0005, RFC-0009 "Running in Docker", ADR-0012): the API, the live streams and the two
# pages. The runs and scenes are mounted READ ONLY at /data/runs and /data/scenes; the host's state folder (the one
# index) is mounted at /index. Pictures for the agent (Chromium) stay outside the image.
#
#   docker build -f apps/observatory/Dockerfile -t miniview:local .      # from the repository root: it installs libs/runfile too
#
# The run format is a path source in apps/observatory/pyproject.toml, so the folders sit side by side as they do in the repository.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH MINIVIEW_DATA=/data MINIVIEW_INDEX=/index/index.sqlite PYTHONUNBUFFERED=1
WORKDIR /app
COPY libs/runfile/pyproject.toml ./libs/runfile/pyproject.toml
COPY libs/runfile/src ./libs/runfile/src
COPY apps/observatory/pyproject.toml apps/observatory/uv.lock ./apps/observatory/
WORKDIR /app/apps/observatory
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/observatory/src ./src
COPY apps/observatory/web ./web
RUN uv sync --frozen --no-dev
RUN mkdir -p /index /data

EXPOSE 8070
# the first start indexes every run under /data (1.4 GB took about 3 minutes here), and the server answers only after it
HEALTHCHECK --interval=10s --timeout=3s --retries=3 --start-period=600s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8070/api/v1/health', timeout=2)"
CMD ["miniview", "--data", "/data", "serve", "--host", "0.0.0.0", "--port", "8070"]
