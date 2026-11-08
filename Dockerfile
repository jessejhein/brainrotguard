FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build provenance, shown as the version suffix (see version.py). Empty = detect from git if present.
ARG BRG_BUILD_SHA=""
ENV BRG_BUILD_SHA=${BRG_BUILD_SHA}

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/* \
    && useradd -r -m -s /bin/false appuser && mkdir -p /app/db && chown -R appuser:appuser /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "if [ -f /app/config.yaml ]; then exec python main.py -c /app/config.yaml; else exec python main.py; fi"]
