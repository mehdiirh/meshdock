FROM ghcr.io/astral-sh/uv:0.11.14 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MESHDOCK_DATA_DIR=/data UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini compile_locales.py ./
RUN chmod -R a+rX app alembic alembic.ini compile_locales.py && uv run --no-sync python compile_locales.py && useradd --system --uid 10001 meshdock && mkdir /data && chown meshdock:meshdock /data
USER meshdock
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
