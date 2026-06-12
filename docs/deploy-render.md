# Deploying the sandbox demo (Render) — private, with real callbacks

Stands up **one service** — the API **and** the Merchant Console, same-origin — plus a managed
**Postgres**, behind a **shared password**, with **real pawaPay callbacks** wired. No real money
(sandbox). Everything below is already in the repo (`Dockerfile`, `render.yaml`, the app changes);
you do the signup + secrets + dashboard steps.

---

## What it looks like deployed

```
 you + testers ──(password)──▶  https://<app>.onrender.com/        → redirects to /console/
                                 ├─ Merchant Console (gated)
                                 ├─ API: /transactions, /merchants… (gated)
                                 └─ /webhooks/pawapay  ◀── pawaPay callbacks (signature-verified,
                                                            NOT password-gated)
                                 Managed Postgres (data persists across deploys)
```

One Basic-auth password gates the console + API (username **`drcpay`**). The webhook is exempt
(pawaPay can't send your password; it's verified by signature) and so is `/health`.

---

## Tiers — what it costs (as of June 2026; verify current rates)

Only **Render** still has a real free tier; Railway and Fly are paid-only now.

| Option | Cost | Notes |
|---|---|---|
| **Render free** (this Blueprint) | **$0 to start** | Web service **sleeps after ~15 min idle** → first hit waits 30–50s. Free Postgres expires after **90 days**. Fine for kicking the tires. |
| **Render always-on** | **~$13/mo** | Starter web ($7) + Postgres (~$6). No sleep. |
| **Railway** (alternative) | **~$5/mo** | Flat, usage-based; one-click Postgres; always-on, no sleep. Simplest all-in — same `Dockerfile`, no `render.yaml` (use Railway's dashboard + add a Postgres plugin; it injects `DATABASE_URL`). |
| Fly.io | trial only | Free tier ended; hard trial limits — not recommended for a persistent demo. |

**Recommendation:** start on **Render free** with the Blueprint to validate; switch to Starter (or **Railway** for the cheapest always-on) once testers are using it.

---

## Deploy on Render (Blueprint)

1. **Push the repo** (the `Dockerfile` + `render.yaml` are committed): `git push origin main`.
2. **Render → New → Blueprint** → connect the GitHub repo. Render reads `render.yaml` and creates
   the **web service** + the **Postgres** together, and wires `DRCPAY_DATABASE_URL` automatically.
3. **Set the two secrets** (service → Environment): `DRCPAY_PAWAPAY_API_TOKEN` and
   `DRCPAY_PAWAPAY_PUBLIC_KEY`. (Both are marked `sync: false`, so the Blueprint won't ask for them.)
4. **Grab the password:** `DRCPAY_BASIC_AUTH_PASSWORD` was auto-generated — copy it from the
   Environment tab. Testers log in with username **`drcpay`** + that password.
5. **Deploy.** Open `https://<your-app>.onrender.com` → it redirects to `/console/` → enter the
   credentials → take a payment, run reconciliation (works the same as local, now persistent).

> If the Blueprint syntax ever drifts, you can instead create the service manually: New → Web
> Service → point at the repo's `Dockerfile`, add a Postgres instance, and set the same env vars.

---

## Wire real-time callbacks (closes the last Phase E gap)

A public URL is exactly what pawaPay needs to call you back — so confirmations arrive on their own
(no more manual "Run reconciliation").

1. **pawaPay dashboard → Developers → Callback URLs:** set all three (Deposits/Payouts/Refunds) to
   `https://<your-app>.onrender.com/webhooks/pawapay`.
2. **Enable signed callbacks** and copy the **public key** → set it as `DRCPAY_PAWAPAY_PUBLIC_KEY`
   in Render (step 3 above).
3. Because Render terminates TLS at your real domain, the signature's `@authority` (the `Host`
   header) matches what pawaPay signs — no tunnel/host-header trickery needed.

> First live callback = the moment we confirm the **callback JSON body shape** (the last
> *provisional* item). If our parser needs a tweak, it's a one-line change in
> `integrations/pawapay/callbacks.py`.

---

## Your part vs. mine

- **Built (in the repo):** `Dockerfile`, `render.yaml`, the entrypoint (runs migrations then
  serves), same-origin console serving, the Basic-auth gate, and `postgres://`→`postgresql+psycopg://`
  URL handling.
- **Yours:** sign up for Render, set the two secret env vars, share the password with testers, and
  do the pawaPay dashboard callback config. (Secrets live in Render's env — never the repo.)
