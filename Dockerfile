# Base image with Python 3.12 (slim version for smaller size)
FROM python:3.12-slim

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Ensure logs are shown in real time (important for Docker logs)
ENV PYTHONUNBUFFERED=1

# Keep uv virtual environment outside /app to avoid being shadowed by bind mounts.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required for some Python packages
# (e.g. gcc for compiling native extensions)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency sync from pyproject + lockfile
RUN pip install --no-cache-dir uv

# Copy project dependency metadata first to leverage Docker layer caching
COPY pyproject.toml uv.lock* ./

# Install runtime + dev dependencies (tests and lint run inside this image)
RUN uv sync --frozen --group dev --no-install-project

# Copy the rest of the application code into the container
COPY . .

# Make entrypoint script executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose the port the FastAPI app will run on
EXPOSE 8000

# Use the entrypoint to run migrations before starting the app
ENTRYPOINT ["/entrypoint.sh"]

# Run migrations and start the app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]