# Agents Assemble — ED Decision Rules Superpower MCP server.
#
# Runtime image for the hackathon submission. Brings up the Superpower
# behind a stdin/stdout MCP transport so the Prompt Opinion platform can
# attach via standard MCP discovery.
#
# Build from the repo root:
#   docker build -f src/healthcraft/agents_assemble/docker/Dockerfile -t agents-assemble/ed-decision-rules .
# Run:
#   docker run -i --rm agents-assemble/ed-decision-rules
FROM python:3.11-slim

LABEL org.opencontainers.image.title="agents-assemble/ed-decision-rules"
LABEL org.opencontainers.image.description="ED Decision Rules MCP Superpower (Prompt Opinion / Agents Assemble 2026)"
LABEL org.opencontainers.image.source="https://github.com/GOATnote-Inc/healthcraft"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install only the runtime deps. We rely on the package's pyproject for the
# transitive set so we never drift from the in-tree source.
COPY pyproject.toml requirements-lock.txt ./
COPY src ./src

RUN pip install --upgrade pip && \
    pip install -e .

# Drop privileges. The Superpower has no need for root inside the container.
RUN useradd --create-home --uid 10001 superpower
USER superpower

# Default command: Streamable-HTTP MCP server on $PORT (default 8080).
# Prompt Opinion attaches by URL (https://host/mcp). Override with the stdio
# entrypoint (``python -m healthcraft.agents_assemble.superpower_decision_rules``)
# when running locally as a stdin/stdout MCP transport.
EXPOSE 8080
CMD ["sh", "-c", "python -m healthcraft.agents_assemble.streamable_http_server --port ${PORT:-8080}"]
