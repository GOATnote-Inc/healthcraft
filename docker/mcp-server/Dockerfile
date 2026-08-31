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

# Run as non-root (matches the agents-assemble image).
RUN useradd --create-home --uid 10001 healthcraft
USER healthcraft

EXPOSE 8000

# Inside the container, 0.0.0.0 is required so the compose network and
# published ports can reach the server; the container boundary (and the
# loopback-only port publishing in docker-compose.yaml) is the exposure
# control. Outside Docker, `python -m healthcraft.mcp.app` defaults to
# 127.0.0.1 unless HEALTHCRAFT_API_TOKEN is set. Startup logs a warning
# when the server is unauthenticated and bound to a non-loopback host.
ENV HEALTHCRAFT_HOST=0.0.0.0
CMD ["python", "-m", "healthcraft.mcp.app"]
