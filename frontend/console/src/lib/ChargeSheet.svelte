<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { fade, scale } from 'svelte/transition'
  import Icon from './Icon.svelte'
  import { api, ApiError } from './api'
  import { t } from './i18n'
  import { money } from './format'
  import { sessionExpired } from './session'
  import { CHARGE_TERMINAL, type Charge } from './types'

  // Creates a charge for `amount`, shows its QR, and polls until the money question is settled.
  let { amount, onclose, onpaid }: { amount: string; onclose: () => void; onpaid: () => void } =
    $props()

  let charge = $state<Charge | null>(null)
  let error = $state('')
  let timer: ReturnType<typeof setInterval> | undefined

  const POLL_MS = 3000

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = undefined
    }
  }

  async function poll(id: string) {
    try {
      const c = await api.getCharge(id)
      charge = c
      if (CHARGE_TERMINAL.has(c.status)) {
        stop()
        if (c.status === 'paid') onpaid()
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        stop()
        sessionExpired()
      }
      /* transient errors: keep polling - the next tick may succeed */
    }
  }

  onMount(async () => {
    try {
      const c = await api.createCharge(amount)
      charge = c
      timer = setInterval(() => poll(c.id), POLL_MS)
    } catch {
      error = $t.err_api
    }
  })
  onDestroy(stop)

  const statusLabel = $derived(charge ? $t.charge_states[charge.status] : '')
  const isPaid = $derived(charge?.status === 'paid')
  const isDeclined = $derived(charge?.status === 'declined')
</script>

<div
  class="scrim"
  role="button"
  tabindex="0"
  aria-label={$t.charge_cancel}
  onclick={onclose}
  onkeydown={(e) => e.key === 'Escape' && onclose()}
  transition:fade={{ duration: 150 }}
></div>
<div class="center">
<div
  class="sheet card"
  role="dialog"
  aria-modal="true"
  aria-label={$t.charge_title}
  transition:scale={{ duration: 180, start: 0.94 }}
>
  <button class="x" onclick={onclose} aria-label={$t.charge_cancel}><Icon name="plus" size={20} /></button>

  {#if error}
    <div class="state">
      <p class="msg bad">{error}</p>
      <button class="btn btn-ghost wide" onclick={onclose}>{$t.charge_cancel}</button>
    </div>
  {:else if !charge}
    <div class="state"><p class="msg muted">{$t.charge_waiting}</p></div>
  {:else if isPaid}
    <div class="state">
      <div class="tick"><Icon name="check" size={34} stroke={2.4} /></div>
      <h2 class="display big">{money(charge.amount, charge.currency)}</h2>
      <p class="msg ok">{$t.charge_paid}</p>
      <button class="btn btn-primary wide" onclick={onclose}>{$t.charge_done}</button>
    </div>
  {:else}
    <h2 class="display title">{$t.charge_title}</h2>
    <p class="lead">{$t.charge_show(money(charge.amount, charge.currency))}</p>
    <div class="qrwrap">
      <img class="qr" src={charge.qr_svg_path} alt={$t.charge_title} />
    </div>
    <div class="status" class:bad={isDeclined}>
      {#if !isDeclined}<span class="dot"></span>{/if}
      {isDeclined ? $t.charge_declined : statusLabel}
    </div>
    <button class="btn btn-ghost wide" onclick={onclose}>{$t.charge_cancel}</button>
  {/if}
</div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(2px);
    z-index: 40;
  }
  .center {
    position: fixed;
    inset: 0;
    z-index: 41;
    display: grid;
    place-items: center;
    padding: 16px;
    pointer-events: none; /* clicks outside the sheet fall through to the scrim (closes) */
  }
  .sheet {
    pointer-events: auto;
    width: min(400px, 100%);
    padding: 26px 24px 22px;
    text-align: center;
  }
  .x {
    position: absolute;
    top: 14px;
    right: 14px;
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
    transform: rotate(45deg);
  }
  .x:hover {
    color: var(--ink);
  }
  .title {
    font-size: 19px;
    font-weight: 600;
    color: var(--ink);
  }
  .lead {
    font-size: 13.5px;
    color: var(--muted);
    margin: 6px 0 16px;
    line-height: 1.5;
  }
  .qrwrap {
    display: grid;
    place-items: center;
    background: var(--qr-bg);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 16px;
  }
  .qr {
    width: 200px;
    height: 200px;
    display: block;
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--muted);
    margin: 16px 0;
  }
  .status.bad {
    color: var(--danger);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--brand);
    animation: blink 1.1s ease-in-out infinite;
  }
  @keyframes blink {
    0%,
    100% {
      opacity: 0.3;
    }
    50% {
      opacity: 1;
    }
  }
  .state {
    padding: 14px 0 4px;
  }
  .big {
    font-size: 40px;
    font-weight: 600;
    color: var(--ink);
    margin: 12px 0 2px;
  }
  .tick {
    width: 66px;
    height: 66px;
    border-radius: 50%;
    background: var(--okbg);
    color: var(--ok);
    display: grid;
    place-items: center;
    margin: 0 auto;
  }
  .msg {
    font-size: 15px;
    font-weight: 600;
    margin: 6px 0 18px;
  }
  .msg.ok {
    color: var(--ok);
  }
  .msg.bad {
    color: var(--danger);
  }
  .msg.muted {
    color: var(--muted);
  }
  .wide {
    width: 100%;
    padding: 13px;
  }
</style>
