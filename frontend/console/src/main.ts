import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

const app = mount(App, {
  target: document.getElementById('app')!,
})

// Register the service worker for an installable, offline-shell PWA. It only caches the built
// shell (see public/sw.js) - never API/money data. Not in dev (it would shadow the API proxy).
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/console/sw.js', { scope: '/console/' }).catch(() => {
      /* SW is a progressive enhancement - the app works without it */
    })
  })
}

export default app
