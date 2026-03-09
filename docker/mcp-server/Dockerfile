FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Install healthcraft with MCP and Docker dependencies
RUN pip install --no-cache-dir -e ".[mcp,docker]"

EXPOSE 8000

CMD ["uvicorn", "healthcraft.mcp.server:app", "--host", "0.0.0.0", "--port", "8000"]
