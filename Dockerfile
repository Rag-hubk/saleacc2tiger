FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY src /app/src
COPY scripts /app/scripts
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY .env.example /app/.env.example

RUN mkdir -p /app/data/storage/exports /app/keys

CMD ["python", "-m", "saleacc_bot.main"]
