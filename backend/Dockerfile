FROM python:3.11-slim

# Install system dependencies for psycopg (PostgreSQL driver) and Pillow
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 5000

CMD ["gunicorn", "app:app", "--config", "gunicorn.conf.py"]
