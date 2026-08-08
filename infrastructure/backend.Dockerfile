FROM python:3.12-slim

WORKDIR /app
COPY backend/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .
COPY backend /app

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
