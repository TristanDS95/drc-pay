import { readable } from 'svelte/store'

// Tiny hash router - no dependency, keeps the bundle lean. The nav links are plain #hash
// anchors; this turns the current hash into a screen id. '#charge' is an action, not a screen,
// so it falls through to 'overview' (the take-a-payment screen).
export type Screen = 'overview' | 'payments' | 'customers' | 'settings' | 'dev'

const SCREENS = new Set<Screen>(['overview', 'payments', 'customers', 'settings', 'dev'])

function current(): Screen {
  const h = location.hash.replace(/^#/, '') as Screen
  return SCREENS.has(h) ? h : 'overview'
}

/** The active screen, derived from location.hash and kept in sync with back/forward + nav clicks. */
export const route = readable<Screen>(current(), (set) => {
  const on = () => set(current())
  window.addEventListener('hashchange', on)
  return () => window.removeEventListener('hashchange', on)
})

export function go(screen: Screen): void {
  location.hash = screen
}
