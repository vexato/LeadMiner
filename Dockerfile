FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home leadminer \
    && install -d -o leadminer -g leadminer -m 0700 /data/results

COPY config config
COPY core core
COPY extractors extractors
COPY models models
COPY output output
COPY scrapers scrapers
COPY storage storage
COPY migrations migrations
COPY api api
COPY utils utils
COPY alembic.ini main.py ./

USER leadminer
ENV LEADMINER_OUTPUT_DIR=/data/results
CMD ["python", "main.py", "--help"]
