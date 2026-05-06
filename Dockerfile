FROM python:3.12-slim

# Install system deps (for asyncpg, cryptography, Node for Vercel CLI)
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    libpq-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Vercel CLI globally
RUN npm install -g vercel@latest

WORKDIR /app

# Copy dependency files first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the app
COPY . .

# Expose port (Railway injects $PORT)
EXPOSE 8000

# Run migrations then start the server
CMD alembic upgrade head && \
    uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 2
