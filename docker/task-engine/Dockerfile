FROM python:3.12-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY configs/ ./configs/
COPY system-prompts/ ./system-prompts/

# Install healthcraft with dev dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Evaluation results directory
RUN mkdir -p /app/results/trajectories

VOLUME ["/app/results"]

ENTRYPOINT ["python", "-m", "healthcraft.eval_runner"]
