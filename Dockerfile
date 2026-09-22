# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.3 AS uv-bin

FROM python:3.11-slim

WORKDIR /app

# uv resolves/downloads the Python graph substantially faster than pip. The
# cache mount survives Docker layer invalidation, so changing dependency
# metadata does not force every wheel to be downloaded again.
COPY --from=uv-bin /uv /uvx /bin/
COPY pyproject.toml ./
RUN python - <<'PY' > /tmp/requirements-server.txt
import tomllib

with open("pyproject.toml", "rb") as handle:
    project = tomllib.load(handle)["project"]

requirements = [
    *project.get("dependencies", []),
    *project.get("optional-dependencies", {}).get("server", []),
]
print("\n".join(requirements))
PY
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --requirements /tmp/requirements-server.txt

# Source changes happen after the expensive dependency layer, so normal UI /
# Python edits do not reinstall the dependency graph. The server runs directly
# from /app and therefore does not need an editable package install.
COPY . .

# Frontend assets are built reproducibly in the Node stage; Node is not kept
# in the runtime image.
COPY --from=web-build /web/dist /app/web/dist

ENV OBSIDIAN_VAULT_PATH=/vault
ENV WIKI_JOB_DB=/ingest-state/jobs.db

EXPOSE 8765 8787

CMD ["fastmcp", "run", "mcp_server.py:mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8765"]
