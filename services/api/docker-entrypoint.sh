#!/bin/sh
# Container entrypoint: apply DB migrations (if a database is configured), then serve.
set -e

if [ -n "$DRCPAY_DATABASE_URL" ]; then
  echo "[entrypoint] applying database migrations…"
  alembic upgrade head
fi

echo "[entrypoint] starting uvicorn on :${PORT:-8000}"
# --proxy-headers so request.base_url reflects the real https host behind Railway's proxy
# (used for the QR's pay-page URL and the callback signature's @authority).
exec uvicorn drc_pay_api.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*"
