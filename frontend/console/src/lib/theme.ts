import { writable } from 'svelte/store'

export type Theme = 'light' | 'dark'
const KEY = 'interpay.theme'

function initial(): Theme {
  const saved = localStorage.getItem(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** The active theme. Persisted, and applied to <html data-theme> so the CSS tokens switch. */
export const theme = writable<Theme>(initial())

theme.subscribe((t) => {
  document.documentElement.setAttribute('data-theme', t)
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* private mode - the attribute still applies for this session */
  }
})

export const toggleTheme = () => theme.update((t) => (t === 'dark' ? 'light' : 'dark'))
