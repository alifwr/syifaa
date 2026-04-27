FROM python:3.12-slim

WORKDIR /app

# build-essential + libpq-dev for asyncpg/psycopg compilation; curl for healthchecks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir .

EXPOSE 8000

# Apply migrations on every start; safe because alembic upgrade is idempotent.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
