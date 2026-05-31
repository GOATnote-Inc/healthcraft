FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
# Bake the world seed config into the image so it boots standalone (the
# docker-compose bind-mount of ../configs is only a local-dev override).
COPY configs/ ./configs/

# Install healthcraft with MCP and Docker dependencies
RUN pip install --no-cache-dir -e ".[mcp,docker]"

EXPOSE 8000

CMD ["uvicorn", "healthcraft.mcp.app:app", "--host", "0.0.0.0", "--port", "8000"]
