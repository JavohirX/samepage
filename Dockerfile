FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin samepage \
    && mkdir -p /app /data/media \
    && chown -R samepage:samepage /data/media
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=samepage:samepage . .
USER samepage
EXPOSE 8000
CMD ["python", "-m", "samepage.ops.entrypoint"]

FROM runtime AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
USER samepage
CMD ["pytest", "-q"]

FROM python:3.12-slim AS oracle
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1
WORKDIR /oracle
COPY requirements-oracle.txt tools/oracle_statsmodels.py ./
RUN pip install --no-cache-dir -r requirements-oracle.txt
CMD ["python", "oracle_statsmodels.py", "--toml", "/work/.dogfood.toml", "--base", "http://app:8000"]
