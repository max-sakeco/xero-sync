FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# Health check
HEALTHCHECK --interval=5s --timeout=3s \
  CMD curl -f http://localhost:8080/ || exit 1

CMD gunicorn --bind 0.0.0.0:8080 wsgi:app --log-level debug --capture-output --enable-stdio-inheritance
