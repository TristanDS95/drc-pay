"""Request/response shapes for the HTTP API (Pydantic)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateTransactionRequest(BaseModel):
    payer_msisdn: str
    payee_msisdn: str
    amount: str  # major units, e.g. "10.00"
    currency: str = "USD"
    # Demo control: which simulated pawaPay outcome to play out.
    scenario: str = "success"  # success | payout_fail | collection_fail | refund_fail


class LedgerLine(BaseModel):
    account: str
    direction: str
    amount: str
    currency: str


class TransactionResponse(BaseModel):
    id: str
    payer_msisdn: str
    payee_msisdn: str
    amount: str
    fee: str
    currency: str
    state: str
    history: list[str]
    ledger: list[LedgerLine]
    # Human-readable operations trace (empty on plain reads; populated on create).
    trace: list[str] = Field(default_factory=list)
