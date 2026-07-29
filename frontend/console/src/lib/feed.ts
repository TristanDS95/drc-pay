import { derived, writable } from 'svelte/store'
import { api, ApiError } from './api'
import { sessionExpired } from './session'
import { needsConfirm } from './format'
import type { Transaction } from './types'

// One source of transactions for the whole app. Overview, Payments and Customers all read this
// instead of each polling /transactions on its own timer.

export type FeedStatus = 'loading' | 'ok' | 'error'

export const transactions = writable<Transaction[]>([])
export const feedStatus = writable<FeedStatus>('loading')

let timer: ReturnType<typeof setInterval> | undefined
const POLL_MS = 6000

/** Fetch once. A 401 means the cookie expired mid-session → drop to login. */
export async function refreshFeed(): Promise<void> {
  try {
    transactions.set(await api.listTransactions())
    feedStatus.set('ok')
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      sessionExpired()
      return
    }
    // Only surface the error on the very first load; a blip mid-session keeps the last-known rows.
    feedStatus.update((s) => (s === 'loading' ? 'error' : s))
  }
}

/** Begin polling (idempotent). Call once the merchant is authed. */
export function startFeed(): void {
  if (timer) return
  refreshFeed()
  timer = setInterval(refreshFeed, POLL_MS)
}

export function stopFeed(): void {
  if (timer) {
    clearInterval(timer)
    timer = undefined
  }
  transactions.set([])
  feedStatus.set('loading')
}

/** Merchant attests they received (or didn't) an on-net payment, then refreshes. Shared by
 * Overview and Payments. Throws are swallowed except a 401, which drops to login. */
export async function confirmReceipt(id: string, received: boolean): Promise<void> {
  try {
    await api.confirmOnNet(id, received)
    await refreshFeed()
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) sessionExpired()
  }
}

// --- derived views ------------------------------------------------------------

/** Newest first (the store keeps insertion order; the backend has no timestamp field yet). */
export const newestFirst = derived(transactions, ($t) => [...$t].reverse())

/**
 * Headline numbers for the Payments screen. No per-row timestamp exists in the API yet, so these
 * are session/all-time totals, not "today" - label them as totals until a created_at lands.
 */
export const stats = derived(transactions, ($t) => {
  let receivedMinor = 0
  let currency = 'USD'
  let awaiting = 0
  for (const t of $t) {
    if (t.state === 'payout_succeeded') {
      // Sum minor units off the major string to avoid float drift (e.g. "9.55" → 955).
      receivedMinor += Math.round(parseFloat(t.merchant_nets) * 100)
      currency = t.currency
    }
    if (needsConfirm(t)) awaiting += 1
  }
  return {
    received: (receivedMinor / 100).toFixed(2),
    currency,
    payments: $t.length,
    awaiting,
  }
})

export interface CustomerRow {
  msisdn: string
  provider: string | null
  count: number
  totalMinor: number
  currency: string
}

/** Unique payers, aggregated from transactions - the Customers screen. Most active first. */
export const customers = derived(transactions, ($t) => {
  const map = new Map<string, CustomerRow>()
  for (const t of $t) {
    const row = map.get(t.customer_msisdn) ?? {
      msisdn: t.customer_msisdn,
      provider: t.customer_provider,
      count: 0,
      totalMinor: 0,
      currency: t.currency,
    }
    row.count += 1
    if (t.state === 'payout_succeeded') row.totalMinor += Math.round(parseFloat(t.amount) * 100)
    if (!row.provider) row.provider = t.customer_provider
    map.set(t.customer_msisdn, row)
  }
  return [...map.values()].sort((a, b) => b.count - a.count)
})
