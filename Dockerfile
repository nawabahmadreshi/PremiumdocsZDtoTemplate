# Production Dockerfile for Aquera Premium Documentation Hub
# Supports Render, Heroku, DigitalOcean, and AWS ECS

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5001

# Set work directory
WORKDIR /app

# Install system dependencies needed for Playwright/Chromium and building tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    libglib2.0-0 \
    nss-plugin-pem \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies first to optimize Docker layer caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its Chromium browser dependencies
RUN playwright install --with-deps chromium

# Copy the rest of the application code
COPY . /app/

# Expose port (Render/Heroku override this via $PORT environment variable)
EXPOSE 5001

# Run the application with Gunicorn binding dynamically to the provided PORT
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5001} --workers 2 --threads 4 --timeout 120 main:app"]
