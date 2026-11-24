FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /bin/bash vektor
WORKDIR /app

COPY --from=builder --chown=vektor:vektor /app/.venv /app/.venv
COPY --from=builder --chown=vektor:vektor /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV VEKTOR_HOST="0.0.0.0"
ENV VEKTOR_PORT="8000"

USER vektor
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]