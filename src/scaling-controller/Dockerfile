# Build
FROM python:3.14-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN pip install uv && uv sync --no-cache --frozen --compile

# Runtime
FROM python:3.14-slim AS runtime
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY src/ src/
RUN pip install python-openstackclient
CMD ["/app/.venv/bin/python", "src/main.py"]
