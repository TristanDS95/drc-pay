import { writable } from 'svelte/store'
import { api } from './api'

// The developer/diagnostics view only exists where the sandbox `/demo` router is mounted (local +
// sandbox). Probing /demo/credentials tells us: a 2xx means we're off the real-money path, a 404
// (real prod, router not mounted) means hide the dev tools entirely.
export const devcapable = writable(false)

export async function probeDev(): Promise<void> {
  try {
    await api.demoCredentials()
    devcapable.set(true)
  } catch {
    devcapable.set(false)
  }
}
