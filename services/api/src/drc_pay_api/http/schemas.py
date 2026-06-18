"""Request/response shapes for the HTTP API (Pydantic)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateTransactionRequest(BaseModel):
    customer_msisdn: str  # the customer paying
    merchant_id: str  # the registered merchant being paid
    amount: str  # major units, e.g. "10.00" — the sticker price the customer pays
    currency: str = "USD"
    # Demo control: which simulated pawaPay outcome to play out (ignored on the live rail).
    scenario: str = "success"  # success | payout_fail | collection_fail | refund_fail
    # Demo control (simulator only): when True, do NOT play the outcome out — leave the
    # transaction pending, as if pawaPay accepted it but its callback never arrived. Used to
    # demonstrate the reconciliation safety net healing a "stuck" payment.
    defer: bool = False
    # Optional customer-operator override (pawaPay provider code). When omitted, the
    # server resolves it via pawaPay predict-provider if a live rail is configured.
    customer_provider: str | None = None


class LedgerLine(BaseModel):
    account: str
    direction: str
    amount: str
    currency: str


class TransactionResponse(BaseModel):
    id: str
    customer_msisdn: str
    merchant_id: str | None = None
    merchant_name: str | None = None
    merchant_msisdn: str  # the merchant's settlement number
    amount: str  # what the customer paid
    fee: str  # our fee (MDR); the merchant nets amount − fee
    currency: str
    state: str
    history: list[str]
    ledger: list[LedgerLine]
    # Resolved operators + pawaPay operation ids (None on the simulator / before issued).
    customer_provider: str | None = None
    merchant_provider: str | None = None
    deposit_id: str | None = None
    payout_id: str | None = None
    refund_id: str | None = None
    # Human-readable operations trace (empty on plain reads; populated on create).
    trace: list[str] = Field(default_factory=list)


class MerchantResponse(BaseModel):
    id: str
    name: str
    short_code: str
    settlement_msisdn: str
    settlement_provider: str  # pawaPay operator code, e.g. "AIRTEL_COD" — the operator the merchant uses
    status: str
    ussd_string: str  # "*123*1001#" — what the customer dials
    tel_uri: str  # "tel:*123*1001%23" — the USSD dial-through (the eventual static-till QR payload)
