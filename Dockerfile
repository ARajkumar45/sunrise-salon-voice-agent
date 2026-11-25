# One image for both the web server and the agent worker.
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/srv/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY data ./data
RUN useradd --create-home appuser && chown -R appuser /srv
USER appuser

# Same image plus pytest and the tests. Used by: docker compose --profile test run --rm tests
FROM app AS test
USER root
RUN uv sync --frozen --no-install-project
COPY tests ./tests
COPY scripts ./scripts
RUN chown -R appuser /srv/tests /srv/scripts
USER appuser
CMD ["pytest", "-v"]
