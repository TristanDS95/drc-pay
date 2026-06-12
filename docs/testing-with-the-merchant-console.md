# Testing with the Merchant Console (pawaPay sandbox)

A plain-language guide to driving the app against the **live pawaPay sandbox** using the web
Merchant Console. No real money moves — the sandbox simulates everything.

---

## 1. Start it up

You need two things running, from `drc-pay/`:

```bash
# 1) the API — from services/api, with the venv active and your sandbox token in .env
cd services/api && source .venv/bin/activate
uvicorn --app-dir src drc_pay_api.main:app --port 8000      # IMPORTANT: --app-dir src

# 2) the console — in a second terminal, from the repo root
python3 -m http.server 5501 --directory tooling/merchant-console
```

Then open **http://localhost:5501**. The badge top-right should read **LIVE · SANDBOX**, and the
health check (`http://localhost:8000/health`) should say `"environment":"sandbox"`. If it says
`local`, your token isn't being picked up — check `services/api/.env`.

> The console talks to the API at `http://127.0.0.1:8000`. To point it elsewhere, add `?api=` to
> the URL, e.g. `http://localhost:5501/?api=https://my-tunnel.example`.

---

## 2. What you're looking at

| Panel | What it is |
|---|---|
| **Top bar** | Pick which merchant you're "acting as" (Alpha Gas Station / Beta Pop-up Store). |
| **Merchant card** | That merchant's QR + till code — what a customer would scan or dial. |
| **Take a payment** | Enter a customer number + amount, press **Take payment**. |
| **Reconciliation — the safety net** | How many payments are waiting on pawaPay, and a **Run reconciliation now** button that polls pawaPay and finishes them. |
| **Payments** | The live feed of this merchant's payments. **Click any row** to see its full detail. |
| **Operations console** (right) | A live trace of every step — collect, settle, ledger postings, reconciliation. |

Click a payment in the feed to open its **detail**: the money breakdown (customer paid, our fee,
merchant nets), the pawaPay operation ids, the **state history**, and the **double-entry ledger**
(the real source of truth).

---

## 3. The basic test (a successful payment, end to end)

1. Leave the customer number at **`243813456789`** (a Vodacom M-Pesa *success* test number) and the
   amount at `10.00`. Press **Take payment**.
2. The payment appears as **Awaiting payment** — pawaPay accepted it, but (just like real life)
   nothing is instant; it's waiting on confirmation. The safety-net counter shows **1**.
3. Press **Run reconciliation now**. It polls pawaPay, sees the deposit completed, and moves the
   payment to **Settling** (it has now sent the money on to the merchant).
4. Press **Run reconciliation now** again. The settlement confirms → **Paid**. The counter is back
   to **0**.
5. Click the payment in the feed. You'll see the full ledger: customer −10.00 → clearing → merchant
   +9.90 and our fee +0.10. That's a complete cross-network payment on real sandbox rails.

> **Why two clicks?** Each sweep advances one leg (collect, then settle). In production a callback
> or a scheduled sweep does this automatically — here you click it so you can *watch* it happen.

---

## 4. Test numbers — the customer number decides everything

The **customer number** you type picks both the **network** and the **outcome**. Numbers ending in
**`789`** succeed; other endings simulate specific failures.

**Successful payments (ends in 789):**

| Customer number | Network |
|---|---|
| `243813456789` | Vodacom M-Pesa |
| `243973456789` | Airtel |
| `243893456789` | Orange |

**Failure cases (Vodacom shown; Airtel uses `24397…`, Orange uses `24389…`):**

| Customer number | What happens after you reconcile |
|---|---|
| `243813456019` | Declined — payer limit reached |
| `243813456029` | Declined — payer not found |
| `243813456039` | Declined — payment not approved |
| `243813456049` | Declined — insufficient balance |
| `243813456069` | Declined — unspecified failure |

To see a **failure flow**: take a payment with (say) `243813456049`, then **Run reconciliation** —
the payment moves to **Declined** and no money moves. (Source for these numbers:
`docs.pawapay.io/v2/docs/test_numbers`.)

> **Amounts:** USD is accepted by all three networks; keep it between about `0.50` and `2500`.

---

## 5. Things to know

- **Nothing is instant on the live rail.** Every payment lands pending and is completed by
  reconciliation (or, later, by a pawaPay callback once we wire the webhook tunnel). That's real
  asynchronous behaviour, not a quirk of the demo.
- **The merchants always settle successfully** in this demo — their numbers are sandbox
  *payout-success* numbers. Testing a *settlement* failure (which triggers an auto-refund to the
  customer) means pointing a merchant at a payout-failure number; ask and we can wire a quick way
  to do that.
- **Reconciliation is global.** "Run reconciliation now" heals every pending payment, not just the
  one you just made.
- **This control is sandbox-only.** `POST /demo/reconcile` is blocked in production by design;
  there, reconciliation runs from an authenticated scheduler instead.
