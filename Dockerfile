FROM python:3.11-slim

WORKDIR /app

# Install build dependencies for compiling any C extensions (e.g. SQLAlchemy, fastembed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy packaging files first to leverage Docker cache
COPY pyproject.toml .

# Install dependencies (fastmcp must be installed via the pyproject or directly if missing)
RUN pip install --no-cache-dir -e .

# Copy the rest of the server code
COPY . .

# Set necessary environment variables
ENV OBSIDIAN_VAULT_PATH=/vault
ENV WIKI_JOB_DB=/data/jobs.db

# Expose the standard port
EXPOSE 8765

# Run the MCP server
CMD ["fastmcp", "run", "mcp_server.py:mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8765"]
