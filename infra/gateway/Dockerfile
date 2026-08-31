FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 knowledge-dump
WORKDIR /app
COPY pyproject.toml constraints-gateway.txt README.md ./
COPY apps ./apps
RUN python -m pip install -c constraints-gateway.txt '.[postgres]'

USER knowledge-dump
EXPOSE 8787
CMD ["knowledge-dump-gateway", "serve", "--host", "0.0.0.0", "--port", "8787"]
