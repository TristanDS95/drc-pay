import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

// The console is served same-origin by the API under /console/ (DRCPAY_CONSOLE_DIR points at the
// built dist), so every asset URL must be relative to that base. Dev runs at the root on :5173
// and proxies the API to the local backend on :8010.
export default defineConfig({
  base: '/console/',
  plugins: [svelte(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Every backend path the console calls - forwarded to the running API in dev so the app
      // is same-origin exactly like production.
      '/auth': 'http://127.0.0.1:8010',
      '/transactions': 'http://127.0.0.1:8010',
      '/charges': 'http://127.0.0.1:8010',
      '/merchants': 'http://127.0.0.1:8010',
      '/signup': 'http://127.0.0.1:8010',
      '/public': 'http://127.0.0.1:8010',
      '/demo': 'http://127.0.0.1:8010',
    },
  },
})
