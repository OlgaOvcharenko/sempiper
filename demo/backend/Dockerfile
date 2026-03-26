# Build from repo root so we can use pyproject.toml + poetry.lock.
# Run: docker compose -f demo/docker-compose.yml up (from repo root) or from demo/ with context ../..
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml poetry.lock ./
COPY sempipes ./sempipes
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-root --no-dev
COPY demo/backend/ ./
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
