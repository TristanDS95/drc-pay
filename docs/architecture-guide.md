# DRC Pay - A New User's Guide to the System

What it does, how it is built, and how it all connects - in plain language.

> This Markdown file is the **source of truth** for the guide.
> The Word version (`DRC-Pay-Architecture-Guide.docx`) is **generated from it** for human reading - regenerate it after editing this file:
> `pandoc docs/architecture-guide.md -o docs/DRC-Pay-Architecture-Guide.docx`

## Contents

1. What is DRC Pay?
2. Payment process
3. Front-end
4. Back-end
5. Money rules and standards
6. Payment rails (pawaPay)
7. Same-network payments (on-net)
8. Codebase walkthrough
9. How it all connects (end to end)
10. Where the records live (the database)
11. How it is packaged and hosted
12. How we keep it correct
13. The stack
14. Glossary
15. Where to go next

## 1. What is DRC Pay?

DRC Pay lets a shop in the Democratic Republic of the Congo (DRC) accept mobile-money payments from any customer, no matter which network that customer uses - Vodacom M-Pesa, Airtel Money, or Orange Money.
The customer does not need our app or even an internet connection: they pay by scanning the shop's QR code, or by dialing a short code on a basic phone.

**Important system principles:**

- **Pure pass-through** - money flows from the customer, through our payment partner, to the merchant.
  We never hold anyone's money - we only orchestrate the movement.
- **The merchant absorbs the fee** - the customer pays the price on the sticker; the merchant receives that amount minus the fee.
  The fee is called the MDR (Merchant Discount Rate).
  Today the MDR only covers our partner's cost - we keep no margin yet (see section 5).
- **No app for the customer** - a customer pays by scanning a QR code or dialing USSD (the `*123#`-style menu that works on any phone).
  Only the merchant uses an app - a web page we call the Merchant Console.
- **Same-network payments never touch us** - when the customer and merchant are on the same network, the customer pays the merchant directly on that operator's own rail, and we only record and confirm the sale (see section 7).

## 2. Payment process

1. **The merchant posts a charge.** In the Merchant Console the merchant enters the amount; the system creates a *charge* and shows a QR code that carries that charge.
2. **Scan or dial.** The customer scans the QR (which opens a simple web page showing exactly that amount - the customer cannot change it) or dials the merchant's USSD code on a basic phone.
3. **Pick a network and pay.** The customer chooses their mobile-money network and confirms.
4. **Cross-network: collect, then settle.** Our system asks the payment partner (pawaPay) to collect the money from the customer's wallet (the first "leg"), then to send the money, minus the fee, to the merchant's mobile-money account (the second leg).
5. **Same-network: hand off.** If customer and merchant are on the same network, we instead show the customer how to pay the merchant directly on that operator (their till code when they have one, else their number); the merchant confirms receipt in the Console.
6. **Confirm.** pawaPay tells us the real outcome of each leg moments later (these messages are called callbacks).
   The merchant's screen and the customer's screen both update to "Paid" in real time.
7. **Safety net.** If settlement fails after we already collected, the customer is automatically refunded in full.
   If a confirmation message ever goes missing, a background "reconciliation" process re-checks the truth with pawaPay so nothing is left stuck.

## 3. Front-end

Ours is currently very simple: two single web pages written in plain HTML (the page's structure), CSS (its styling), and JavaScript (the small bit of code that makes it interactive).
There is no heavy framework and no build step - you can open the files and read them top to bottom.

### The Merchant Console

Folder: `frontend/merchant-console/`.
This is the shop owner's cockpit.
It creates a charge and shows its QR ("Charge by QR"), displays a live feed of transactions, lets them drill into the accounting detail of any payment, lists same-network payments awaiting their "Confirm received" tap, and keeps a de-emphasized reconcile fallback.
It is protected by a password.

### The Customer page

Folder: `frontend/customer-app/`.
This is what a payer sees after scanning the QR code.
The amount is already locked in from the charge; they pick their network, pay, and watch the result confirm in real time - or, for a same-network payment, they get the hand-off instructions to pay the merchant directly.
There is no login - a customer has no account.
It also includes a USSD dial simulator so you can preview the basic-phone experience.

**Why so simple?**
A payments product should not depend on a complicated front-end toolchain before it needs one.
Plain pages load instantly and are easy to host and to reason about.
A polished native phone app is deliberately left for later (see `docs/future-dev.md`).

## 4. Back-end

Ours lives in `backend/` and is written in Python.
It exposes an API, which is just a set of web addresses the front-end pages can call to get things done (for example, "take this payment" or "what is the status of this transaction?").

- **FastAPI** - the framework (a toolkit) that turns our Python functions into that web API.
  It is modern, fast, and documents its own endpoints.
- **Uvicorn** - the small web server program that actually runs FastAPI and answers incoming requests.
- **Pydantic** - a library that checks the shape of every request coming in and every response going out (for example, that an amount really is a number) - a guardrail against bad data near real money.

### Hexagonal architecture

Ours uses a "hexagonal" (also called "ports-and-adapters") arrangement, which means:
the pure money logic sits in the middle and knows nothing about the web, the database, or pawaPay.
Those outside things "plug in" around it through clearly defined connection points.
Every channel a payment can arrive through - the web API, USSD - is a thin caller into the same core; money logic is never reimplemented per channel.

## 5. Money rules and standards

These are the rules that keep the money correct.
They live in the folder of "pure" logic and are the most heavily tested part of the system.

- **Money is whole numbers, never decimals** - computers are famously bad at decimal math (0.1 + 0.2 is not exactly 0.3 to a computer).
  That is unacceptable with real money, so internally we store every amount as a whole number of the smallest unit (cents), tagged with a currency.
- **Double-entry ledger** - the accounting method where every movement is recorded twice: once as where money came from, once as where it went.
  The two sides must balance exactly; if they do not, the system refuses to record it.
  This ledger, not any single status field, is our source of truth.
- **State machine** - a precise map of the stages a payment can be in (initiated, collection pending / succeeded / failed, payout pending / succeeded / failed, refund pending, refunded, manual review) and which moves between them are allowed.
  Any move that is not on the map is rejected as a bug.
  This makes it impossible for a payment to be "half done" without a recorded reason.
- **Idempotency** - a guarantee that doing the same money request twice (say, because the network hiccuped and the app retried) never charges twice.
  Each request carries a unique key; a repeat with the same key returns the original result instead of making a new charge.
- **Reconciliation** - the safety net.
  We assume confirmation messages can occasionally go missing.
  A "sweep" periodically finds any payment still waiting on an answer and re-checks the truth directly with pawaPay, then finishes it.
  It can run safely alongside the normal flow without double-acting.
- **Never trust the client** - the amount, the fee, and who gets paid are always re-derived on the server; nothing the customer's browser sends is taken at face value.

**The fee model in one paragraph:**
the customer pays the sticker amount; the merchant nets that amount minus the fee (the MDR).
pawaPay's real per-leg cost is booked to an expense account (`expense:pawapay`) as each leg completes; whatever is left of the MDR after cost - the margin - goes to revenue (`revenue:fees`).
Today the MDR exactly equals pawaPay's cost, so revenue is exactly zero: we keep nothing, and the books say so honestly.
A failed settlement refunds the customer in full; the already-spent collection fee stays in expense, so a refunded payment correctly shows as a small loss.

## 6. Payment rails (pawaPay)

*Rails* is industry slang for the underlying network that actually moves money.
Rather than connect to each mobile-money operator ourselves, we rent pawaPay, a company whose service handles Vodacom, Airtel, and Orange for us.
We call their API (their set of web addresses) to start each money movement.

- **Deposit / Payout / Refund** - pawaPay's three operations: a deposit collects money from the customer; a payout sends money to the merchant; a refund returns money to the customer if settlement failed.
- **Asynchronous** - meaning the answer does not come back immediately.
  When we start a payment, pawaPay first says "accepted," then tells us the real outcome a little later.
  We are built around this delay.
- **Webhook / Callback** - a webhook (or callback) is pawaPay calling us back at a web address we gave them, to deliver that later outcome.
  It is the reverse of us calling them.
- **Signed callback** - to be sure a callback genuinely came from pawaPay and was not faked or tampered with, pawaPay attaches a cryptographic signature.
  We verify that signature (using pawaPay's public key, which our app fetches automatically) before trusting the message.
  Anything unsigned or altered is rejected.
- **Both ways of learning an outcome** - the pushed callback and the polled reconciliation check - funnel into a single piece of code, so a payment finishes the same way no matter which path delivered the news.

## 7. Same-network payments (on-net)

When the customer and the merchant are on the *same* network, routing through pawaPay would pay two legs of fees for money that never needed to leave that operator.
So for these payments we step out of the money's way entirely (decision record: ADR 0009):

- The customer pays the merchant **directly on the operator's own rail** - to the merchant's till code when they have one, else to their number.
- Our system **facilitates and records**: it shows the customer exactly how to pay, records the sale as *awaiting confirmation*, and the merchant taps **"Confirm received"** in the Console once the operator's SMS arrives.
- The fee is **zero** - we never touch the money.
- Every "paid" transaction carries a **provenance** tag: *merchant-attested* (the merchant vouched for it) or *rail-verified* (pawaPay confirmed it moved).
  The books never overstate how sure we are.

Cross-network payments still go through pawaPay, the licensed partner that keeps us non-custodial.

## 8. Codebase walkthrough

Where everything lives.
The back-end is the package `backend/src/drc_pay_api/`; the two web pages live under `frontend/`.

| Path | What it does |
| --- | --- |
| `backend/src/drc_pay_api/` | The back-end package (Python / FastAPI): the money logic and all channels. |
| `  domains/` | Pure business rules - no web, database, or vendor knowledge. |
| `  domains/ledger/` | Money as whole numbers + the double-entry ledger. |
| `  domains/transactions/` | The state machine, the pricing rules, and the two payment spines: the `Orchestrator` (cross-network via pawaPay) and the `OnNetOrchestrator` (same-network record-and-confirm). |
| `  domains/merchants/` | What a merchant is (id, name, till code, where to settle). |
| `  domains/charges/` | A charge: the merchant-posted amount a QR carries. |
| `  application/` | Shared services every channel calls (start a payment, route on-net vs cross-network, apply an outcome, verify webhooks). |
| `  adapters/` | Storage plug-ins: `memory.py` (in-memory) and `sql.py` (PostgreSQL). |
| `  integrations/pawapay/` | All pawaPay-specific code (client, signatures, simulator). |
| `  ussd/` | The basic-phone (USSD) channel. |
| `  jobs/reconciliation/` | The safety-net sweep that re-checks stuck payments. |
| `  http/` | The web layer: API routes and the callback receiver. |
| `  container.py` | The composition root - where the real adapters are chosen and wired; every channel goes through it. |
| `  main.py · config.py · seed.py` | App startup, settings, and demo-merchant seeding. |
| `frontend/merchant-console/` | The gated web cockpit (merchant side). |
| `frontend/customer-app/` | The public scan-to-pay page (customer side). |

## 9. How it all connects (end to end)

Tying the pieces together, here is a successful cross-network payment as it moves through the code:

1. The Customer page (front-end) sends a "pay" request for a charge to a public web address in `http/public_routes.py`.
2. That route calls `start_merchant_payment` in `application/payments.py` - the shared entry point.
   `application/routing.py` decides here whether this is a same-network payment (hand-off, section 7) or a cross-network one (continue below).
3. The `Orchestrator` looks up the merchant, then asks the pawaPay client to collect from the customer.
   It records the new stage in the state machine and the database.
4. Moments later pawaPay sends a signed callback to `http/webhook_routes.py`; we verify the signature and call `apply_outcome`, which advances the payment and writes balanced entries to the ledger.
5. The same happens for the settlement leg.
   When it completes, the Merchant Console (which refreshes every few seconds) and the Customer page (which polls for status) both show "Paid."
6. The USSD channel follows the exact same path from step 2 onward - it just collects the amount through a phone menu instead of a web form.

## 10. Where the records live (the database)

- **Database** - an organized store of records that survives restarts.
  Ours keeps merchants, charges, transactions, and the ledger.
- **PostgreSQL ("Postgres")** - the specific, battle-tested database we use in the cloud.
  On our host it is a managed add-on, so we do not run it ourselves.
- **Alembic** - a tool that manages the database's structure over time.
  When we change what we store, Alembic applies that change in a controlled, repeatable way - automatically, every time we deploy.
- **In-memory store** - for local development and most tests the app runs with no database at all (records live in memory and vanish on restart); a few storage-layer tests use SQLite, a tiny file-based database, so they run instantly with nothing to set up.
- A deployed environment **refuses to start** without a working database - it never silently falls back to the in-memory store.

## 11. How it is packaged and hosted

- **Docker** - a way to bundle the whole application - the Python service and both web pages - into one self-contained package (an "image") that runs the same everywhere.
  One package serves all three from a single web address.
- **Railway** - the hosting service that runs our Docker package in the cloud, provides the Postgres database, and gives us a public web address.
  We chose it because it is cheap and simple.
  Because it is just a Docker image, we can move it elsewhere later with little fuss.
- **AWS (the future home)** - Amazon Web Services is the eventual production target for the real launch; the infrastructure plan lives in `docs/future-dev.md`.
- **Environment variables** - settings handed to the app from outside the code (for example, the pawaPay token and the demo password).
  This is how we keep secrets out of the code and the shared repository entirely.
- A shared password protects the merchant side of the hosted demo; the customer pages and the pawaPay callback stay open, because a payer has no login and pawaPay cannot type a password.
  A deployed environment refuses to start without that password set.

## 12. How we keep it correct

- **ruff** - checks code style and catches common mistakes automatically.
- **mypy (strict)** - verifies that the code's data types line up, catching whole classes of bugs before the program ever runs.
- **pytest** - the automated test suite; the money rules carry the heaviest testing.
  It runs entirely offline against an in-process pawaPay simulator, plus an opt-in set of tests against pawaPay's real sandbox.
- **Git and GitHub** - Git is version control - it records the history of every change.
  GitHub is the website that hosts that history.
  When we push a change to GitHub, the host automatically rebuilds and redeploys the app.
- **CI (Continuous Integration)** - an automatic check that runs the style, type, and test tools - plus a secret scan - on every change, so nothing broken slips through.

## 13. The stack

A one-line summary of every layer, top to bottom:

| Layer | What we use, in one line |
| --- | --- |
| Front-end | Plain HTML / CSS / JavaScript - two simple web pages (merchant + customer) |
| Back-end language | Python - the money engine and the web API |
| Web framework | FastAPI, run by Uvicorn - turns Python into the web API |
| Data checking | Pydantic - guards the shape of every request and response |
| Money core | Custom double-entry ledger + state machine - correctness for real money |
| Payment rails | pawaPay - moves the actual mobile money (Vodacom / Airtel / Orange); same-network payments go merchant-direct instead |
| Extra channel | USSD - pay from a basic, no-internet phone |
| Database | PostgreSQL (managed by Alembic); in-memory for local dev and tests |
| Packaging | Docker - one image holding the API and both web pages |
| Hosting | Railway today; AWS is the eventual production home |
| Secrets / config | Environment variables - no secret ever lives in the code |
| Quality tools | ruff, mypy (strict), pytest, Git / GitHub, CI |

## 14. Glossary

Every technical term used in this guide, in plain words:

| Term | Plain meaning |
| --- | --- |
| API | A set of web addresses one program offers so other programs can ask it to do things. |
| Architecture | How the code is organized into parts. |
| Asynchronous | The answer comes back later, not immediately. |
| Back-end | The part that runs on a server, out of sight, doing the real work. |
| Callback / Webhook | An outside service calling us back to deliver a later result. |
| Charge | The merchant-posted amount a payment QR carries; the customer pays exactly it. |
| CI (Continuous Integration) | Automatic checks (style, types, tests) run on every code change. |
| CSS | The language that styles a web page (colors, layout, fonts). |
| Database | An organized store of records that survives restarts. |
| Deposit / Payout / Refund | Collect from the customer / send to the merchant / return to the customer. |
| Docker | A self-contained package of the app that runs the same everywhere. |
| Double-entry ledger | The accounting method where every movement is recorded twice and must balance. |
| Environment variable | A setting handed to the app from outside the code (used for secrets). |
| Framework | A toolkit that provides the structure for building something (here, the web API). |
| Front-end | The part you see and click in a web browser. |
| Git / GitHub | Version control (the change history) and the website that hosts it. |
| Hexagonal architecture | Pure logic in the middle; the web, database, and partners plug in around it. |
| HTML | The language that defines a web page's structure and content. |
| Idempotency | Doing the same request twice never charges twice. |
| JavaScript | The code that makes a web page interactive. |
| Ledger | The official record of money movements. |
| MDR (Merchant Discount Rate) | Our fee, absorbed by the merchant. |
| On-net | A payment where customer and merchant are on the same mobile-money network. |
| Pass-through | Money flows through us to the merchant; we never hold it. |
| Provenance | How sure we are a payment happened: rail-verified (pawaPay confirmed) or merchant-attested (the merchant vouched). |
| Rails | The underlying network that actually moves money (here, pawaPay). |
| Reconciliation | A safety net that re-checks stuck payments directly with pawaPay. |
| Signed callback | A callback carrying a cryptographic signature proving it really came from pawaPay. |
| State machine | A map of allowed stages and the moves between them. |
| Till | A merchant's short pay code on an operator ("buy goods" number) or in our USSD menu. |
| USSD | The `*123#`-style phone menu that works on any phone with no internet. |

## 15. Where to go next

- `docs/DEVLOG.md` - the current build status and what is planned next; deploy specifics live in its "Deploy" section.
- `README.md` - the project's front page: status, layout, and how to run it.
- `docs/adr/` - Architecture Decision Records: short notes explaining why key choices were made.
- `docs/future-dev.md` - the longer-horizon plans (mobile app, admin dashboard, AWS).
- `CLAUDE.md` - the engineering standards, tracked in this repo.
