FROM python:3.12-slim

# Install system deps
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

# Make startup script executable
RUN chmod +x /app/start.sh

# Expose port (Railway injects $PORT)
EXPOSE 8000

# Use startup script (handles migrations + server)
CMD ["/app/start.sh"]
