# ChronoHive admission API — eval container.
# Stdlib-only service; no pip dependencies.
FROM python:3.12-slim

# Non-root runtime user.
RUN useradd -m -u 10001 chronohive

WORKDIR /app
COPY src/ ./src/
COPY scripts/demo_admission.py ./scripts/demo_admission.py
COPY service/chronohive_api.py ./service/chronohive_api.py
COPY service/entrypoint.sh ./service/entrypoint.sh
COPY tools/ ./tools/
COPY TOC.md ./TOC.md

# Writable dirs for the non-root user. Named volumes inherit this ownership.
RUN mkdir -p /run/secrets /var/log/chronohive /var/lib/chronohive \
    && chown -R chronohive:chronohive /app /run/secrets /var/log/chronohive \
       /var/lib/chronohive \
    && chmod +x /app/service/entrypoint.sh
USER chronohive

# Operator-mounted at deploy time (never baked into the image):
#   /run/secrets/api_keys.json       key entries (hashes only, see gen_key.py)
#   /var/log/chronohive              audit log volume
#   /var/lib/chronohive              TOC acceptance store volume
ENV PORT=8080 \
    CH_API_KEYS_FILE=/run/secrets/api_keys.json \
    CH_AUDIT_LOG=/var/log/chronohive/audit.jsonl \
    CH_TOC_STATE=/var/lib/chronohive/toc_acceptances.json \
    CH_TOC_PATH=/app/TOC.md

EXPOSE 8080

# Health probe for orchestrators.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/v1/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["/app/service/entrypoint.sh"]
