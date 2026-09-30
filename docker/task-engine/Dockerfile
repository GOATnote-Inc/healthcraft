FROM python:3.12-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md LICENSE constraints-security.txt ./
COPY src/ ./src/
COPY configs/ ./configs/
COPY system-prompts/ ./system-prompts/
COPY docker/task-engine/run_eval.sh /app/run_eval.sh

# Install healthcraft with dev dependencies
RUN pip install --no-cache-dir -c constraints-security.txt -e ".[dev]"

# Evaluation results directory
RUN mkdir -p /app/results/trajectories

VOLUME ["/app/results"]

ENTRYPOINT ["bash", "/app/run_eval.sh"]
