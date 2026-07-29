// API response shapes — mirror the backend Pydantic schemas (backend/src/drc_pay_api/http).
// Money is always a major-unit STRING ("12.50"), server-derived; never parse it into a float
// for arithmetic (see CLAUDE.md money rules) - only for display.

export interface Merchant {
  id: string
  name: string
  short_code: string
  settlement_msisdn: string
  settlement_provider: string | null // pawaPay operator code, e.g. "AIRTEL_COD"
  status: string
  ussd_string: string // "*123*1001#" - what the customer dials
  tel_uri: string // "tel:*123*1001%23" - the dial-through the static-till QR encodes
  operator_till: string | null
}

export interface LedgerLine {
  account: string
  direction: string
  amount: string
  currency: string
}

// A transaction state, mirrored from domains/transactions/state_machine.py.
export type TxState =
  | 'initiated'
  | 'collection_pending'
  | 'collection_succeeded'
  | 'collection_failed'
  | 'payout_pending'
  | 'payout_succeeded'
  | 'payout_failed'
  | 'refund_pending'
  | 'refunded'
  | 'manual_review'

export interface Transaction {
  id: string
  customer_msisdn: string
  merchant_id: string | null
  merchant_name: string | null
  merchant_msisdn: string
  amount: string
  fee: string
  merchant_nets: string
  currency: string
  state: TxState
  history: string[]
  ledger: LedgerLine[]
  customer_provider: string | null
  merchant_provider: string | null
  deposit_id: string | null
  payout_id: string | null
  refund_id: string | null
  provenance: string // "rail_verified" | "merchant_attested"
  trace: string[]
}

export type ChargeStatus =
  | 'awaiting_payment'
  | 'processing'
  | 'paid'
  | 'declined'
  | 'refunded'
  | 'review'

export interface Charge {
  id: string
  merchant_id: string
  merchant_name: string
  amount: string
  currency: string
  status: ChargeStatus
  transaction_id: string | null
  qr_svg_path: string
}

// A charge status is terminal once the money question is settled (paid, or a failure the
// merchant should see). The poll stops here.
export const CHARGE_TERMINAL: ReadonlySet<ChargeStatus> = new Set<ChargeStatus>([
  'paid',
  'declined',
  'refunded',
  'review',
])
