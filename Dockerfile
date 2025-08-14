FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | POETRY_HOME=/opt/poetry python3 - && \
    cd /usr/local/bin && \
    ln -s /opt/poetry/bin/poetry && \
    poetry config virtualenvs.create false

# Copy poetry configuration files
COPY pyproject.toml poetry.lock* ./

# Ensure the lock file matches the current pyproject before installing
RUN poetry lock --no-interaction --no-ansi \
 && poetry install --no-interaction --no-ansi --only main --no-root

# Ensure CPU-only PyTorch to avoid missing CUDA libraries in this container
RUN pip uninstall -y torch torchvision torchaudio || true && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
      torch==2.0.1+cpu torchvision==0.15.2+cpu

# Copy the application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app
ENV FLASK_RUN_PORT=8080
ENV FLASK_ENV=production

# Expose the port
EXPOSE 8080

# Run the application
CMD ["python", "run.py"] 