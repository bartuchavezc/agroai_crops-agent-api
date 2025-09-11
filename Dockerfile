# Multi-stage build for smaller final image
FROM python:3.10-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    curl \
    build-base \
    libffi-dev \
    openssl-dev \
    postgresql-dev \
    jpeg-dev \
    zlib-dev \
    freetype-dev \
    lcms2-dev \
    openjpeg-dev \
    tiff-dev \
    tk-dev \
    tcl-dev \
    harfbuzz-dev \
    fribidi-dev \
    libimagequant-dev \
    libxcb-dev \
    musl-dev \
    linux-headers

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | POETRY_HOME=/opt/poetry python3 - && \
    cd /usr/local/bin && \
    ln -s /opt/poetry/bin/poetry && \
    poetry config virtualenvs.create false && \
    poetry config installer.max-workers 10

# Copy poetry configuration files
COPY pyproject.toml poetry.lock* ./

# Install dependencies
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Production stage
FROM python:3.10-alpine AS production

# Install only runtime dependencies
RUN apk add --no-cache \
    postgresql-libs \
    libffi \
    jpeg \
    zlib \
    freetype \
    lcms2 \
    openjpeg \
    tiff \
    harfbuzz \
    fribidi \
    libimagequant \
    libxcb

# Create non-root user
RUN addgroup -g 1000 appuser && adduser -D -s /bin/sh -u 1000 -G appuser appuser

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8080
ENV PYTHONPATH=/app

# Switch to non-root user
USER appuser

# Expose the port
EXPOSE 8080

# Run the application
CMD ["python", "run.py"] 