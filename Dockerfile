# Multi-arch base (amd64 and arm64), pinned by tag and by the digest of its multi-arch index.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime

LABEL org.opencontainers.image.title="samepage" \
      org.opencontainers.image.description="Self-hosted hackathon submission and judging portal" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A real user and group with a passwd entry. It owns only the media directory.
RUN groupadd --gid 10001 samepage \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/samepage --shell /usr/sbin/nologin samepage \
 && mkdir -p /app /data/media \
 && chown -R samepage:samepage /data/media

WORKDIR /app

# Wheels only, no compilers: a missing wheel fails the build instead of compiling.
COPY requirements.txt .
RUN pip install --only-binary=:all: -r requirements.txt

# The app, fixtures.json (the demo seed) and the tests. .dockerignore keeps out local state.
COPY . .

# WhiteNoise serves STATIC_ROOT, so collect at build time (no database needed).
RUN python manage.py collectstatic --noinput -v 0

USER 10001:10001
EXPOSE 8000

# CMD, not ENTRYPOINT: 'docker compose run --rm app python manage.py <command>' runs the command.
CMD ["python", "-m", "samepage.ops.entrypoint"]

# pytest against Postgres: docker compose --profile test run --rm test
FROM runtime AS test
USER root
COPY requirements-dev.txt .
RUN pip install --only-binary=:all: -r requirements-dev.txt
USER 10001:10001
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "-rs"]

# The outside check, in its own image: docker compose --profile oracle run --rm oracle
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS oracle
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid 10001 oracle \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin oracle
WORKDIR /oracle
COPY requirements-oracle.txt .
RUN pip install --only-binary=:all: -r requirements-oracle.txt
COPY tools/oracle_statsmodels.py .
USER 10001:10001
CMD ["python", "oracle_statsmodels.py", "--toml", "/work/.dogfood.toml", "--base", "http://app:8000"]
