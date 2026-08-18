FROM python:3.12-slim

RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app
COPY backend/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .
COPY --chown=app:app backend /app

USER app
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
