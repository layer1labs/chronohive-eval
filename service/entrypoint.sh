#!/bin/sh
# Eval container entrypoint: mint a local API key on first boot if none
# exists, print it to stdout (visible in `docker compose logs`), then run
# the API. The raw key is printed only here, never baked into the image.
set -eu

KEYS_FILE="${CH_API_KEYS_FILE:-/run/secrets/api_keys.json}"

if [ ! -s "$KEYS_FILE" ]; then
  echo "No API keys found at $KEYS_FILE - generating a local eval key..."
  python3 /app/tools/gen_key.py --id eval-local-01 --days 30 \
      --existing "$KEYS_FILE"
  echo "Save the RAW API KEY printed above; it is shown only once."
fi

exec python3 /app/service/chronohive_api.py
