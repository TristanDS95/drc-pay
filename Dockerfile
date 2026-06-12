# DRC Pay — single-container sandbox/demo image: the FastAPI API + the static Merchant
# Console, served same-origin. Build context is the repo root (it needs both services/api
# and tooling/merchant-console).
FROM python:3.13-slim

WORKDIR /app

# Install the API as a real package (non-editable — the container path has no spaces, so the
# editable-install gotcha doesn't apply here). psycopg[binary] + cryptography ship wheels, so
# no system build deps are needed.
COPY services/api/pyproject.toml ./pyproject.toml
COPY services/api/src ./src
RUN pip install --no-cache-dir .

# Alembic config + migrations (applied at startup) and the static console.
COPY services/api/alembic.ini ./alembic.ini
COPY services/api/migrations ./migrations
COPY tooling/merchant-console ./console
COPY services/api/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# The app serves the console from here when DRCPAY_CONSOLE_DIR is set.
ENV DRCPAY_CONSOLE_DIR=/app/console
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
