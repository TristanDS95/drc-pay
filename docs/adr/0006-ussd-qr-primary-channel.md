# ADR 0006 - USSD / QR as the primary customer channel

- **Status:** Accepted (2026-06-11). Reverses the earlier "USSD phased to v2" decision.
- **Context:** In the DRC the paying customer frequently has **no mobile data** and may have no
  smartphone, but mobile-money authorisation runs on the cellular **signalling channel**
  (USSD/SIM-toolkit), not data. The merchant, by contrast, is online (app/dashboard). So the
  channel that reaches the most customers is USSD, not a data app - and it is MVP-critical, not
  a later phase.
- **Decision:** The **primary customer flow is customer-initiated USSD**. The customer **scans
  the merchant's QR** - which encodes a `tel:` USSD dial-through (`tel:*123*1001%23`) - or
  **dials the till** (`*123*1001#`) on any phone; **no customer app or internet**; the customer
  authorises with their mobile-money PIN via the **operator's own prompt** (we never see it).
  The handler parses the aggregator's **full accumulated text** (`till*amount*choice`), so a
  scanned/dialed pre-filled code jumps straight ahead (dial-through fast-path). A
  **merchant-initiated "charge by customer number" push** is a **kept fallback** (for operators
  without USSD pull, or non-scanning customers). We **rent the USSD bearer** (Africa's Talking /
  Infobip) - we do **not** self-host (the same per-operator VAS/WASP + ARPTC barrier as building
  our own rails; see the USSD-gateway research).
- **Consequences:**
  - Adds the `ussd/` channel, per-merchant payment codes (`application/payment_codes.py`), and a
    printable QR (`/merchants/{id}/qr.svg`, via `segno`). Both channels are **thin callers** into
    the same `Orchestrator` via `application.start_merchant_payment`.
  - **iOS blocks scan-to-USSD** and feature phones can't scan → a merchant sticker always shows
    the **QR + the printed dialable till**; those customers dial it manually.
  - Channel costs (flagged): ~**$0.034 per USSD session** + shortcode rental (~**$1k setup +
    ~$600/mo**), on top of pawaPay's fees. The real aggregator integration + a real shortcode
    are **team actions** (we don't sign up). Research:
    `../../../drc-mvp-research/02-findings/cross-cutting/ussd-gateway-providers.md`.
- **Alternatives considered:** smartphone/web QR checkout (needs customer data - excludes the
  offline majority); client-side USSD automation, Hover-style (no fee capture / not in the money
  path); self-hosted USSD gateway (per-operator + regulator-gated - rejected for the MVP).
