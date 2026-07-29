<script lang="ts">
  import Icon from '../lib/Icon.svelte'
  import { api } from '../lib/api'
  import { t } from '../lib/i18n'
  import { refreshFeed } from '../lib/feed'
  import { money } from '../lib/format'
  import type { Merchant } from '../lib/types'

  // Sandbox-only diagnostics, ported from the live console's "dev" view: simulate the full payment
  // lifecycle (happy path + each failure branch), walk the real USSD menu, force reconciliation,
  // and watch every operation in a live trace. Deliberately English-only (a developer surface).
  let { merchant }: { merchant: Merchant } = $props()

  const SCENARIOS = [
    { id: 'success', label: 'Success' },
    { id: 'collection_fail', label: 'Collection fails' },
    { id: 'payout_fail', label: 'Payout fails → refund' },
    { id: 'refund_fail', label: 'Refund fails → review' },
  ]

  let cust = $state('243970000789')
  let amount = $state('10.00')
  let scenario = $state('success')
  let defer = $state(false)
  let busy = $state(false)

  let ussdAmt = $state('10.00')
  let ussdBusy = $state(false)

  let trace = $state<string[]>([])
  const push = (lines: string[]) => (trace = [...trace, ...lines])

  async function takePayment() {
    if (busy) return
    busy = true
    try {
      const tx = await api.createTransaction({ customer_msisdn: cust.trim(), amount, scenario, defer })
      push([
        `▸ POST /transactions · ${money(tx.amount, tx.currency)} · scenario=${scenario}${defer ? ' · defer' : ''}`,
        ...tx.trace,
        `state → ${tx.state}`,
      ])
      await refreshFeed()
    } catch (e) {
      push([`✕ take payment failed: ${e instanceof Error ? e.message : 'error'}`])
    } finally {
      busy = false
    }
  }

  async function reconcile() {
    if (busy) return
    busy = true
    try {
      const r = await api.reconcile()
      push([
        `🔁 POST /demo/reconcile · swept ${r.swept} · resolved ${r.resolved}`,
        ...r.items.map((i) => `reconcile · ${i.kind} ${i.transaction_id.slice(0, 8)}… → ${i.disposition}`),
      ])
      await refreshFeed()
    } catch (e) {
      push([`✕ reconcile failed: ${e instanceof Error ? e.message : 'error'}`])
    } finally {
      busy = false
    }
  }

  async function ussdDial() {
    if (ussdBusy) return
    ussdBusy = true
    const sid = `sim-${trace.length}-${cust}`
    const code = merchant.short_code
    const steps = ['', code, `${code}*${ussdAmt}`, `${code}*${ussdAmt}*1`]
    push([`📟 USSD dial · ${cust}`])
    try {
      for (const text of steps) {
        const wire = await api.ussd({ session_id: sid, msisdn: cust.trim(), text })
        push([`ussd · ${wire.replace(/\s+/g, ' ').trim()}`])
        if (wire.startsWith('END')) break
      }
      await refreshFeed()
    } finally {
      ussdBusy = false
    }
  }
</script>

<main class="page">
  <div class="pagehead">
    <h1 class="display">{$t.dev_title}</h1>
    <p class="sub">{$t.dev_sub}</p>
  </div>

  <section class="grid">
    <!-- Simulate a payment -->
    <div class="card">
      <h2 class="ch">Simulate a payment</h2>
      <label class="l" for="d-cust">Customer number</label>
      <input id="d-cust" bind:value={cust} inputmode="tel" />
      <div class="two">
        <div>
          <label class="l" for="d-amt">Amount (USD)</label>
          <input id="d-amt" bind:value={amount} inputmode="decimal" />
        </div>
        <div>
          <label class="l" for="d-sc">Outcome</label>
          <select id="d-sc" bind:value={scenario}>
            {#each SCENARIOS as s}<option value={s.id}>{s.label}</option>{/each}
          </select>
        </div>
      </div>
      <label class="chk"><input type="checkbox" bind:checked={defer} /> Defer (leave pending for reconcile)</label>
      <button class="btn btn-primary go" disabled={busy} onclick={takePayment}>Simulate payment</button>
    </div>

    <!-- USSD + reconcile -->
    <div class="card">
      <h2 class="ch">Feature phone (USSD)</h2>
      <label class="l" for="d-uamt">Amount the customer dials</label>
      <input id="d-uamt" bind:value={ussdAmt} inputmode="decimal" />
      <button class="btn btn-ghost go" disabled={ussdBusy} onclick={ussdDial}>
        <Icon name="phone" size={16} /> Walk the USSD menu
      </button>
      <div class="rule"></div>
      <h2 class="ch">Reconciliation</h2>
      <p class="hint">Force-check pending payments against pawaPay - nothing stays stuck.</p>
      <button class="btn btn-ghost go" disabled={busy} onclick={reconcile}>
        <Icon name="refresh" size={16} /> Force reconcile
      </button>
    </div>
  </section>

  <!-- Ops trace -->
  <section class="card trace-card">
    <div class="trace-h">
      <h2 class="ch">operations <span>· live trace: collect → settle → refund · reconciliation</span></h2>
      {#if trace.length}<button class="clear" onclick={() => (trace = [])}>clear</button>{/if}
    </div>
    <pre class="trace">{#if trace.length}{trace.join('\n')}{:else}// simulate a payment or dial USSD to trace every operation{/if}</pre>
  </section>
</main>

<style>
  .page {
    width: 100%;
    max-width: 1080px;
    margin: 0 auto;
    padding: 30px 26px 40px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .pagehead h1 {
    font-size: 30px;
    font-weight: 600;
    color: var(--ink);
  }
  .sub {
    font-size: 14px;
    color: var(--muted);
    margin-top: 6px;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .card {
    padding: 22px;
  }
  .ch {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    margin-bottom: 12px;
  }
  .l {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    margin: 10px 0 5px;
  }
  input,
  select {
    width: 100%;
    border: 1.5px solid var(--line2);
    border-radius: 10px;
    padding: 10px 12px;
    background: var(--inputbg);
    color: var(--ink);
    font-size: 15px;
    outline: none;
  }
  input:focus,
  select:focus {
    border-color: var(--brand);
  }
  .two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .chk {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--ink);
    margin: 12px 0 4px;
  }
  .chk input {
    width: auto;
  }
  .go {
    width: 100%;
    padding: 12px;
    margin-top: 14px;
  }
  .rule {
    height: 1px;
    background: var(--line);
    margin: 20px 0;
  }
  .hint {
    font-size: 12.5px;
    color: var(--muted);
    line-height: 1.5;
    margin-bottom: 4px;
  }
  .trace-card {
    padding: 18px 20px;
  }
  .trace-h {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .trace-h .ch {
    margin: 0;
  }
  .trace-h .ch span {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 500;
    color: var(--faint);
  }
  .clear {
    background: none;
    border: none;
    color: var(--brand-text);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .trace {
    background: var(--canvas);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 14px 16px;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
    line-height: 1.7;
    color: var(--ink);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 320px;
    overflow-y: auto;
    margin: 0;
  }
  @media (max-width: 820px) {
    .page {
      padding: 20px 15px 96px;
    }
    .pagehead h1 {
      font-size: 24px;
    }
    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
