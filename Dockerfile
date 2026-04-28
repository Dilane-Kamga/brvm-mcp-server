FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv pip install --system .

# Expose HTTP transport port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/mcp').raise_for_status()" || exit 1

# Run with streamable HTTP transport
CMD ["brvm-mcp", "--transport", "streamable-http", "--port", "8000"]
