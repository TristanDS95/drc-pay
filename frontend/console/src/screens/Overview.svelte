<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import Icon from '../lib/Icon.svelte'
  import NetworkBadge from '../lib/NetworkBadge.svelte'
  import ChargeSheet from '../lib/ChargeSheet.svelte'
  import { api, ApiError, merchantQrPath } from '../lib/api'
  import { t, lang } from '../lib/i18n'
  import { sessionExpired } from '../lib/session'
  import { printSticker } from '../lib/sticker'
  import {
    opName,
    providerToNetwork,
    formatMsisdn,
    money,
    splitAmount,
    pillClass,
    needsConfirm,
  } from '../lib/format'
  import type { Merchant, Transaction } from '../lib/types'

  let { merchant }: { merchant: Merchant } = $props()

  let amount = $state('10.00')
  let chargeOpen = $state(false)
  let chargeAmount = $state('')

  // Feed: first load shows a skeleton; later polls refresh silently and keep old rows on a blip.
  let txns = $state<Transaction[]>([])
  let feedState = $state<'loading' | 'ok' | 'error'>('loading')
  let confirming = $state<Record<string, boolean>>({})
  let feedTimer: ReturnType<typeof setInterval> | undefined

  const FEED_MS = 6000

  // Localized long date - "mardi 28 juillet" / "Tuesday, 28 July".
  const today = $derived(
    new Intl.DateTimeFormat($lang, { weekday: 'long', day: 'numeric', month: 'long' }).format(
      new Date(),
    ),
  )
  const settlesTo = $derived(
    $t.settles_to($opName(merchant.settlement_provider), formatMsisdn(merchant.settlement_msisdn)),
  )
  // Newest first, capped - a merchant scans the last few, not a ledger.
  const rows = $derived([...txns].reverse().slice(0, 40))
  const amt = $derived(splitAmount(amount || '0'))

  async function refresh() {
    try {
      txns = await api.listTransactions()
      feedState = 'ok'
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        sessionExpired()
        return
      }
      if (feedState === 'loading') feedState = 'error' // only surface on the first load
    }
  }

  async function confirm(id: string, received: boolean) {
    if (confirming[id]) return
    confirming = { ...confirming, [id]: true }
    try {
      await api.confirmOnNet(id, received)
      await refresh()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) sessionExpired()
    } finally {
      confirming = { ...confirming, [id]: false }
    }
  }

  function openCharge() {
    const a = amount.trim()
    if (!a) return
    chargeAmount = a
    chargeOpen = true
  }

  function toDialCode() {
    document.getElementById('dial')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  onMount(() => {
    refresh()
    feedTimer = setInterval(refresh, FEED_MS)
  })
  onDestroy(() => feedTimer && clearInterval(feedTimer))
</script>

<main class="page">
  <div class="pagehead">
    <div>
      <h1 class="display">{$t.greet(merchant.name)}</h1>
      <p class="sub">{today} · {settlesTo}</p>
    </div>
    <button class="btn btn-primary head-cta" onclick={openCharge}>
      <Icon name="plus" size={18} /> {$t.tab_charge}
    </button>
  </div>

  <section class="cols">
    <div class="card hero">
      <div class="panel-h">
        <h2 class="display">{$t.take_h2}</h2><span class="tag">{$t.take_tag}</span>
      </div>
      <label class="lbl" for="amt">{$t.amount_label}</label>
      <div class="amount">
        <span class="cur display">$</span>
        <input id="amt" class="display tnum" bind:value={amount} inputmode="decimal" />
        <span class="ccy">USD</span>
      </div>
      <button class="btn btn-primary big" onclick={openCharge}>
        <Icon name="qr" size={18} /> {$t.show_qr}
      </button>
      <button class="btn btn-ghost big" onclick={toDialCode}>
        <Icon name="phone" size={18} /> {$t.feature_phone}
      </button>
      <p class="fine">{$t.take_fine}</p>
    </div>

    <div class="card till" id="dial">
      <div class="panel-h">
        <h2 class="display">{$t.dial_h2}</h2>
        <button
          class="link"
          onclick={() =>
            printSticker(merchant, {
              title: $t.sticker_title(merchant.name),
              lead: $t.sticker_lead,
              body: $t.sticker_body,
            })}
        >
          <Icon name="print" size={15} /> {$t.dial_print}
        </button>
      </div>
      <div class="tillcode display">{merchant.ussd_string}</div>
      <div class="qrwrap">
        <img class="qr" src={merchantQrPath(merchant.id)} alt={$t.dial_h2} />
      </div>
      <p class="fine">{$t.dial_fine}</p>
    </div>
  </section>

  <section class="card feed">
    <div class="panel-h">
      <h2 class="display">{$t.feed_h2}</h2>
      <a class="link" href="#payments">{$t.feed_view_all} <Icon name="arrow-right" size={15} /></a>
    </div>

    {#if feedState === 'loading'}
      <p class="empty">{$t.feed_loading}</p>
    {:else if feedState === 'error'}
      <div class="empty">
        <p>{$t.err_api}</p>
        <button class="btn btn-ghost retry" onclick={() => ((feedState = 'loading'), refresh())}>
          {$t.retry}
        </button>
      </div>
    {:else if rows.length === 0}
      <p class="empty">{$t.feed_empty}</p>
    {:else}
      <ul class="list">
        {#each rows as row (row.id)}
          <li>
            <NetworkBadge network={providerToNetwork(row.customer_provider)} />
            <span class="who">
              <b>{$opName(row.customer_provider)}</b>
              <span class="tt">{formatMsisdn(row.customer_msisdn)}</span>
            </span>
            <span class="amt display tnum">{money(row.amount, row.currency)}</span>
            {#if needsConfirm(row)}
              <span class="actions">
                <button
                  class="btn btn-primary confirm"
                  disabled={confirming[row.id]}
                  onclick={() => confirm(row.id, true)}>{$t.confirm_received}</button
                >
              </span>
            {:else}
              <span class="chip chip-{pillClass(row.state)}">
                {#if row.state === 'payout_succeeded'}<Icon name="check" size={13} stroke={2} /> {/if}
                {$t.states[row.state]}
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</main>

{#if chargeOpen}
  <ChargeSheet
    amount={chargeAmount}
    onclose={() => (chargeOpen = false)}
    onpaid={refresh}
  />
{/if}

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
  .pagehead {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
  }
  h1 {
    font-size: 30px;
    font-weight: 600;
    line-height: 1.05;
    color: var(--ink);
  }
  .sub {
    font-size: 14px;
    color: var(--muted);
    margin-top: 7px;
  }
  .head-cta {
    padding: 11px 16px;
    white-space: nowrap;
  }
  .cols {
    display: grid;
    grid-template-columns: 1.25fr 1fr;
    gap: 16px;
  }
  .card {
    padding: 22px;
  }
  .panel-h {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
  }
  .panel-h h2 {
    font-size: 17px;
    font-weight: 600;
    color: var(--ink);
  }
  .tag {
    font-size: 11px;
    font-weight: 600;
    color: var(--muted);
    background: var(--chip);
    padding: 4px 9px;
    border-radius: 20px;
  }
  .lbl {
    font-size: 12.5px;
    color: var(--muted);
    font-weight: 600;
    display: block;
    margin-bottom: 8px;
  }
  .amount {
    display: flex;
    align-items: center;
    gap: 6px;
    border: 1.5px solid var(--line2);
    border-radius: 14px;
    padding: 12px 16px;
    background: var(--inputbg);
  }
  .amount:focus-within {
    border-color: var(--brand);
  }
  .cur {
    font-size: 26px;
    color: var(--muted);
  }
  .amount input {
    border: none;
    outline: none;
    background: none;
    font-size: 30px;
    font-weight: 600;
    color: var(--ink);
    width: 100%;
  }
  .ccy {
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
    letter-spacing: 0.06em;
  }
  .big {
    width: 100%;
    padding: 15px;
    font-size: 15.5px;
    border-radius: 14px;
    margin-top: 12px;
  }
  .fine {
    font-size: 12.5px;
    color: var(--muted);
    line-height: 1.55;
    margin-top: 12px;
  }
  .link {
    background: none;
    border: none;
    color: var(--brand-text);
    font-weight: 600;
    font-size: 13.5px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    text-decoration: none;
  }
  .till {
    display: flex;
    flex-direction: column;
  }
  .tillcode {
    font-weight: 700;
    font-size: 23px;
    color: var(--brand-text);
    text-align: center;
    margin: 4px 0 14px;
  }
  .qrwrap {
    display: grid;
    place-items: center;
    background: var(--qr-bg);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 18px;
  }
  .qr {
    width: 150px;
    height: 150px;
    display: block;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
    display: grid;
    grid-template-columns: 38px 1fr auto auto;
    align-items: center;
    gap: 14px;
    padding: 13px 4px;
    border-top: 1px solid var(--line);
  }
  .list li:first-child {
    border-top: none;
  }
  .who {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .who b {
    font-size: 14.5px;
    font-weight: 600;
    color: var(--ink);
  }
  .who .tt {
    font-size: 12px;
    color: var(--muted);
  }
  .amt {
    font-weight: 600;
    font-size: 16px;
    color: var(--ink);
  }
  .confirm {
    padding: 7px 12px;
    font-size: 12.5px;
    border-radius: 10px;
  }
  .empty {
    text-align: center;
    color: var(--muted);
    font-size: 13.5px;
    padding: 22px 0 8px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }
  .retry {
    padding: 9px 16px;
    font-size: 13.5px;
  }
  @media (max-width: 820px) {
    .page {
      padding: 20px 15px 96px;
    }
    h1 {
      font-size: 24px;
    }
    .cols {
      grid-template-columns: 1fr;
      gap: 14px;
    }
    .pagehead {
      align-items: flex-start;
    }
    .head-cta {
      display: none;
    }
  }
</style>
