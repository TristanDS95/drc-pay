// The single door to the backend. The console is served same-origin (dev: the Vite proxy in
// vite.config.ts forwards these paths to :8010; prod: the API serves the built dist under
// /console/), so auth rides on the HttpOnly `drcpay_session` cookie - we send `credentials:
// 'same-origin'` and never touch a token in JS. This is deliberately stronger than the old
// console, which kept a bearer token in localStorage (an XSS-reachable secret).

import type { Charge, Merchant, Transaction } from './types'

/** A failed API call. `status === 0` means the request never reached the server (network/API down). */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers: { ...(init.body ? { 'content-type': 'application/json' } : {}), ...init.headers },
    })
  } catch (cause) {
    // Never reached the server - the API is down or the network dropped.
    throw new ApiError(0, cause instanceof Error ? cause.message : 'network error')
  }
  if (!res.ok) {
    // Prefer the server's `detail`, but never surface it raw to end users - callers decide copy.
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body - keep the HTTP status */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  // --- auth ---
  login: (username: string, password: string) =>
    request<{ token: string; merchant: Merchant }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  /** Who the session belongs to. Throws ApiError(401) when not logged in - the caller treats that as "show login". */
  me: () => request<Merchant>('/auth/me'),
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }),

  // --- charges (scan-to-pay) ---
  createCharge: (amount: string) =>
    request<Charge>('/charges', { method: 'POST', body: JSON.stringify({ amount }) }),
  getCharge: (id: string) => request<Charge>(`/charges/${id}`),

  // --- transactions (the live feed + on-net confirm) ---
  listTransactions: () => request<Transaction[]>('/transactions'),
  confirmOnNet: (id: string, received: boolean) =>
    request<Transaction>(`/transactions/${id}/confirm?received=${received}`, { method: 'POST' }),

  // --- reference data ---
  providers: () => request<Record<string, string>>('/public/providers'),
  /** Sandbox-only demo accounts (one-tap login). Deployed prod returns `[]`. */
  demoCredentials: () =>
    request<{ username: string; password: string; provider: string | null }[]>('/demo/credentials'),
}

/** Path to a charge's scannable QR (public SVG; loaded via <img>, so no auth header). */
export const chargeQrPath = (charge: Charge) => charge.qr_svg_path
/** Path to a merchant's static USSD-till QR (public SVG). */
export const merchantQrPath = (merchantId: string) => `/merchants/${merchantId}/qr.svg`
