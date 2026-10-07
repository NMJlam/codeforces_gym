# Dev image: source is bind-mounted by docker-compose, Flask auto-reloads.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
CMD ["uv", "run", "flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "5001", "--debug"]
