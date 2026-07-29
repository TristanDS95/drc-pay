import { writable } from 'svelte/store'
import { api, ApiError } from './api'
import type { Merchant } from './types'

// The auth gate's single source of truth.
// - loading: booting - we don't yet know if there's a session (show a neutral splash, never the login flash).
// - anon: no valid session - show the login screen. `reachable=false` means the API itself was
//   unreachable at boot (not just "logged out"), so the login screen can say so.
// - authed: we know the merchant - show the app.
export type Session =
  | { status: 'loading' }
  | { status: 'anon'; reachable: boolean }
  | { status: 'authed'; merchant: Merchant }

export const session = writable<Session>({ status: 'loading' })

/** Boot from the session cookie. A 401 is the normal "not logged in" case - never an error. */
export async function bootSession(): Promise<void> {
  try {
    const merchant = await api.me()
    session.set({ status: 'authed', merchant })
  } catch (err) {
    const reachable = !(err instanceof ApiError && err.status === 0)
    session.set({ status: 'anon', reachable })
  }
}

/** Exchange credentials for a session (cookie set server-side). Throws ApiError on failure - the caller shows copy. */
export async function login(username: string, password: string): Promise<void> {
  const { merchant } = await api.login(username, password)
  session.set({ status: 'authed', merchant })
}

/** Drop the session. Fire-and-forget server revoke - unreachable or already-revoked, we log out locally either way. */
export async function logout(): Promise<void> {
  try {
    await api.logout()
  } catch {
    /* revoked or unreachable - either way this session is done */
  }
  session.set({ status: 'anon', reachable: true })
}

/** Called when any authed request 401s mid-session (the cookie expired): drop straight to login. */
export function sessionExpired(): void {
  session.set({ status: 'anon', reachable: true })
}
