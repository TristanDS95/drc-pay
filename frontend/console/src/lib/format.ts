import { derived, writable } from 'svelte/store'
import { api } from './api'
import type { Network } from './NetworkBadge.svelte'
import type { TxState } from './types'

// --- provider (network) names -------------------------------------------------
// Fallback map so the UI reads correctly even before /public/providers loads (or if it fails).
const FALLBACK: Record<string, string> = {
  VODACOM_MPESA_COD: 'Vodacom M-Pesa',
  AIRTEL_COD: 'Airtel',
  ORANGE_COD: 'Orange',
}

export const providers = writable<Record<string, string>>({ ...FALLBACK })

/** Hydrate the provider-name map from the server; keep the fallback if it's unreachable. */
export async function loadProviders(): Promise<void> {
  try {
    const map = await api.providers()
    if (map && typeof map === 'object') providers.set({ ...FALLBACK, ...map })
  } catch {
    /* keep the fallback - names still render correctly */
  }
}

/** Reactive operator-name lookup: `$opName('AIRTEL_COD')` → "Airtel". */
export const opName = derived(
  providers,
  ($p) =>
    (code: string | null | undefined): string =>
      (code && $p[code]) || code || '-',
)

/** Provider code → the badge's network id, or 'other' for on-net / unresolved / unknown. */
export function providerToNetwork(code: string | null | undefined): Network | 'other' {
  if (!code) return 'other'
  const c = code.toUpperCase()
  if (c.startsWith('AIRTEL')) return 'airtel'
  if (c.startsWith('VODACOM') || c.includes('MPESA')) return 'vodacom'
  if (c.startsWith('ORANGE')) return 'orange'
  return 'other'
}

// --- money / phone display ----------------------------------------------------
// Amounts arrive as major-unit strings ("12.50"); we only ever split them for display, never
// do arithmetic on the float (see CLAUDE.md).

/** Split "12.50" into { whole: "12", cents: ".50" } so the design can de-emphasize the cents. */
export function splitAmount(amount: string): { whole: string; cents: string } {
  const [whole, cents] = amount.split('.')
  return { whole, cents: cents ? `.${cents}` : '' }
}

/** "$12.50" for USD, else "12.50 CDF". */
export function money(amount: string, currency: string): string {
  return currency === 'USD' ? `$${amount}` : `${amount} ${currency}`
}

/** "243973456789" → "+243 973 456 789". Best-effort grouping; unknown shapes pass through. */
export function formatMsisdn(msisdn: string): string {
  const digits = msisdn.replace(/\D/g, '')
  if (digits.startsWith('243') && digits.length === 12) {
    const n = digits.slice(3)
    return `+243 ${n.slice(0, 3)} ${n.slice(3, 6)} ${n.slice(6)}`
  }
  return msisdn
}

// --- status → pill ------------------------------------------------------------
export type Pill = 'ok' | 'wait' | 'mut' | 'bad'

/** Feed pill colour for a transaction state (mirrors the live console's pillClass). */
export function pillClass(state: TxState): Pill {
  if (state === 'payout_succeeded') return 'ok'
  if (state === 'collection_pending' || state === 'payout_pending' || state === 'refund_pending')
    return 'wait'
  if (state === 'refunded' || state === 'initiated' || state === 'collection_succeeded')
    return 'mut'
  return 'bad'
}

/** An on-net payment the merchant must confirm they received (the only feed action). */
export function needsConfirm(t: { state: TxState; provenance: string }): boolean {
  return t.state === 'collection_pending' && t.provenance === 'merchant_attested'
}
