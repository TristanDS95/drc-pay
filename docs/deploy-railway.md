# Deploying the sandbox demo (Railway)

One service — the API **and** the Merchant Console, same-origin — plus a managed **Postgres**,
behind a **shared password**, with real pawaPay **callbacks**. No real money (sandbox). Everything
in the repo is ready (`Dockerfile`, the app); you do the signup + dashboard steps below.

## What to buy
Railway has **no free tier** (just a one-time $5 trial credit). Get the **Hobby plan — $5/month**
([railway.com/pricing](https://railway.com/pricing)). The fee includes some usage; resource use is
billed per-second beyond that, so a small sandbox demo sits right around the $5 base.

## Deploy (~10 minutes)
1. **Sign up** at **[railway.com](https://railway.com)** — use **"Login with GitHub"** (that's how
   you'll deploy). Subscribe to Hobby.
2. **New Project → Deploy from GitHub repo → `drc-pay`.** Railway detects the `Dockerfile` and
   builds it (first build takes a few minutes).
3. **Add the database:** in the project, **New → Database → PostgreSQL.** Railway provisions it and
   exposes its connection string as the reference `${{Postgres.DATABASE_URL}}`.
4. **Set the web service's variables** (service → **Variables**):

   | Variable | Value |
   |---|---|
   | `DRCPAY_ENVIRONMENT` | `sandbox` |
   | `DRCPAY_PAWAPAY_BASE_URL` | `https://api.sandbox.pawapay.io` |
   | `DRCPAY_PAWAPAY_API_TOKEN` | *your sandbox token* — paste it **here in Railway**, not in chat |
   | `DRCPAY_PAWAPAY_PUBLIC_KEY` | *for callbacks* (secret; you can add this later) |
   | `DRCPAY_BASIC_AUTH_PASSWORD` | *a password you choose* — testers log in with user `drcpay` + this |
   | `DRCPAY_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` ← **this reference wires the database in** |

   (`DRCPAY_CONSOLE_DIR` is already baked into the image — don't set it.)
5. **Get a URL:** service → **Settings → Networking → Generate Domain** → e.g.
   `drc-pay-production.up.railway.app`.
6. **Open it** → log in with `drcpay` + your password → the Merchant Console. Migrations ran
   automatically on deploy (the container entrypoint).

## Wire real-time callbacks (closes the last Phase E gap)
1. **pawaPay dashboard → Developers → Callback URLs:** set all three to
   `https://<your-app>.up.railway.app/webhooks/pawapay`.
2. **Enable signed callbacks**, copy the **public key** → set it as `DRCPAY_PAWAPAY_PUBLIC_KEY`.
   Payments then confirm in real time — no manual reconciliation.

## What I need from you
**Nothing secret.** You set the token + password in Railway's dashboard yourself; they never touch
the chat or the repo. The only thing I need back is the **public URL** once it's live, so we can
point pawaPay's callbacks at it (not a secret).

## Notes
- Railway injects `PORT`; the container already binds it. Optionally set the healthcheck path to
  `/health` (service → Settings).
- It's a Docker image, so it's **portable** — moving to AWS for production later is straightforward.
