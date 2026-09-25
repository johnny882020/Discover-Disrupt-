FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

RUN useradd --create-home appuser && mkdir -p /app/exports && chown appuser /app/exports
USER appuser

EXPOSE 8000
COPY --chown=appuser docker/entrypoint.sh /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "dndlabs.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
