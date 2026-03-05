# Use a slim Python 3.11 base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create directory for recordings
RUN mkdir -p /app/recordings

# Expose port (Daphne default is 8000)
EXPOSE 8000

# Start command using daphne (ASGI support)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "remi_core.asgi:application"]
