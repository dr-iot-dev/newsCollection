FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NUMBA_CACHE_DIR=/tmp/numba-cache
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY maintenance/check_environment.py maintenance/retired-paths.json ./maintenance/
COPY docs/seven-stage-system-design-20261015.md ./docs/
COPY app ./app
RUN python maintenance/check_environment.py && pip install --no-cache-dir . \
    && mkdir /data && chown app:app /data
USER 10001:10001
CMD ["news-weave", "--help"]
FROM base AS test
USER root
RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
COPY maintenance/migrate_ai_selection.py ./maintenance/
USER 10001:10001
CMD ["pytest", "-p", "no:cacheprovider"]
FROM base AS runtime
