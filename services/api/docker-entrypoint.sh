#!/bin/sh
# Container entrypoint: apply DB migrations + seed demo merchants (if a database is
# configured), then serve.
set -e

if [ -n "$DRCPAY_DATABASE_URL" ]; then
  echo "[entrypoint] applying database migrations…"
  alembic upgrade head
  # The QR demo needs the demo merchants to exist, but the Postgres path starts empty
  # (production merchants come via onboarding). The seed self-gates: it only writes off
  # production, so this call is safe to run unconditionally on every deploy.
  echo "[entrypoint] seeding demo merchants…"
  python -m drc_pay_api.seed
fi

echo "[entrypoint] starting uvicorn on :${PORT:-8000}"
# --proxy-headers so request.base_url reflects the real https host behind Railway's proxy
# (used for the QR's pay-page URL and the callback signature's @authority).
exec uvicorn drc_pay_api.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*"
