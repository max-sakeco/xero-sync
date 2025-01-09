FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default port, will be overridden by Railway
ENV PORT=8080

# Make sure the port is available
EXPOSE $PORT

# Use shell form to ensure environment variable is expanded
CMD gunicorn --workers 1 --threads 8 --timeout 0 --bind "0.0.0.0:${PORT}" wsgi:app --log-level debug
