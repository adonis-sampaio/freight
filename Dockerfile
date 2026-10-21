FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not re-resolve the world. The
# list is read from pyproject.toml, so pyproject stays the single source of
# truth for the dependencies.
COPY pyproject.toml README.md ./
RUN python -c "import tomllib, pathlib; \
deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; \
pathlib.Path('/tmp/deps.txt').write_text('\n'.join(deps))" \
    && pip install --no-cache-dir -r /tmp/deps.txt

COPY src ./src

# The package itself, with --no-deps: the dependencies are already installed,
# and re-resolving them here would throw away the caching above.
RUN pip install --no-cache-dir --no-deps .

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn freight_agent.api.app:app --host 0.0.0.0 --port ${PORT}"]
