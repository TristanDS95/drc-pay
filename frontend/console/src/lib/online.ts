import { readable } from 'svelte/store'

// Tracks connectivity so the UI can say "you're offline" calmly instead of just failing requests -
// these merchants are on flaky networks, and a clear banner beats a mysterious spinner.
export const online = readable(navigator.onLine, (set) => {
  const up = () => set(true)
  const down = () => set(false)
  window.addEventListener('online', up)
  window.addEventListener('offline', down)
  return () => {
    window.removeEventListener('online', up)
    window.removeEventListener('offline', down)
  }
})
