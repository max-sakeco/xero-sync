FROM python:3.10-slim

# Install curl and netcat for healthcheck and debugging
RUN apt-get update && apt-get install -y curl netcat-openbsd && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=development
ENV FLASK_DEBUG=1

# Expose the port
EXPOSE 8080

# Create a startup script
COPY <<'EOF' /app/start.sh
#!/bin/bash
echo "Starting application..."
echo "Current directory: $(pwd)"
echo "Files in directory:"
ls -la
echo "Environment variables:"
env
echo "Testing port 8080..."
nc -zv localhost 8080 || echo "Port 8080 not yet available"
echo "Starting Gunicorn..."
exec gunicorn --workers=4 \
    --bind=0.0.0.0:8080 \
    --access-logfile=- \
    --error-logfile=- \
    --log-level=debug \
    --capture-output \
    wsgi:app
EOF

RUN chmod +x /app/start.sh

# Health check
HEALTHCHECK --interval=5s --timeout=3s \
  CMD curl -f http://localhost:8080/ || exit 1

# Start using the script
CMD ["/app/start.sh"]
