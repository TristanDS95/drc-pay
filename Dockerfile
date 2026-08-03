# DRC Pay — single-container sandbox/demo image: the FastAPI API + the static Merchant
# Console, served same-origin. Build context is the repo root (it needs both backend
# and the frontend/ apps).

# ── Stage 1: compile the redesigned console (Vite + Svelte) to static assets. ──────────
# A browser can't read .svelte/.ts, so the redesign has to be built. Node lives only in this
# stage — the runtime image below copies the compiled output and ships no Node (ADR 0011).
FROM node:24-slim AS console-build
WORKDIR /console
# Manifests first: this layer caches until the dependencies themselves change, so an edit to
# a component doesn't re-run npm ci.
COPY frontend/console/package.json frontend/console/package-lock.json ./
RUN npm ci
COPY frontend/console ./
RUN npm run build

# ── Stage 2: the runtime image — Python + the static frontends. ────────────────────────
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

# The redesigned console, compiled in stage 1. It SHIPS in the image but is NOT served yet —
# `DRCPAY_CONSOLE_DIR` still points at the old console below. The cutover is a one-variable
# change in the deploy dashboard (`DRCPAY_CONSOLE_DIR=/app/console-next`), and rollback is
# the same flip back, with no rebuild either way. Building it here (rather than at cutover)
# means the image that gets promoted is the one that was tested. See ADR 0011.
COPY --from=console-build /console/dist ./console-next
COPY backend/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# The app serves the (gated) console, the (public) customer pages, and the internal Staff
# Console (/staff — merchant approvals, behind the same demo gate as the console) from these dirs.
ENV DRCPAY_CONSOLE_DIR=/app/console
ENV DRCPAY_CUSTOMER_DIR=/app/customer-app
ENV DRCPAY_STAFF_DIR=/app/staff-console
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
