# DRC Pay — single-container sandbox/demo image: the FastAPI API + the static Merchant
# Console, served same-origin. Build context is the repo root (it needs both backend
# and the frontend/ apps).
FROM python:3.13-slim

WORKDIR /app

# Install the API as a real package (non-editable — the container path has no spaces, so the
# editable-install gotcha doesn't apply here). psycopg[binary] + cryptography ship wheels, so
# no system build deps are needed.
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/src ./src
RUN pip install --no-cache-dir .

# Alembic config + migrations (applied at startup) and the static console.
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY frontend/merchant-console ./console
COPY frontend/customer-app ./customer-app
COPY frontend/staff-console ./staff-console
COPY backend/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# The app serves the (gated) console, the (public) customer pages, and the internal Staff
# Console (/staff — merchant approvals, behind the same demo gate as the console) from these dirs.
ENV DRCPAY_CONSOLE_DIR=/app/console
ENV DRCPAY_CUSTOMER_DIR=/app/customer-app
ENV DRCPAY_STAFF_DIR=/app/staff-console
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
