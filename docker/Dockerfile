FROM python:3.13-slim

# The build context is the REPO ROOT (see docker-compose: context: ../), so all
# COPY paths below are relative to the repo root, not to docker/.

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        git \
        iputils-ping \
        netcat-openbsd \
        zip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY src/ /app/src/
COPY config/ /app/config/

VOLUME ["/app/logs", "/app/data"]

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Interactive by default: the engine asks for trade confirmation on stdin, and
# the orb-* make targets run the container attached so you can answer.
#     make orb-replay / orb-delayed / orb-live
# or, inside a shell here:
#     python -m trading_engine.main --data-mode replay
CMD ["bash"]
