<script lang="ts">
  import Icon from '../lib/Icon.svelte'
  import StatTile from '../lib/StatTile.svelte'
  import NetworkBadge from '../lib/NetworkBadge.svelte'
  import Qr from '../lib/Qr.svelte'
  import type { Network } from '../lib/NetworkBadge.svelte'

  // Placeholder data for phase 1 - wired to the API in phase 2.
  let amount = $state('10.00')
  const feed: { net: Network; label: string; when: string; amount: string; status: 'ok' | 'wait' }[] = [
    { net: 'airtel', label: 'Airtel', when: '243 ••• 789 · 2 min ago', amount: '$25.00', status: 'ok' },
    { net: 'vodacom', label: 'Vodacom M-Pesa', when: '243 ••• 789 · 14 min ago', amount: '$8.50', status: 'ok' },
    { net: 'orange', label: 'Orange', when: '243 ••• 789 · on-net', amount: '$40.00', status: 'wait' },
    { net: 'airtel', label: 'Airtel', when: '243 ••• 789 · 1 hr ago', amount: '$12.00', status: 'ok' },
    { net: 'vodacom', label: 'Vodacom M-Pesa', when: '243 ••• 789 · 3 hr ago', amount: '$43.00', status: 'ok' },
  ]
</script>

<main class="page">
  <div class="pagehead">
    <div>
      <h1 class="display">Good morning, Alpha</h1>
      <p class="sub">Tuesday, 22 July · settling to <b>Airtel</b> · 243&thinsp;•••&thinsp;789</p>
    </div>
    <button class="btn btn-primary head-cta"><Icon name="plus" size={18} /> New charge</button>
  </div>

  <section class="stats">
    <StatTile label="Received today" value="$128" cents=".50" sub="12% vs yesterday" positive spark />
    <StatTile label="Payments today" value="6" sub="4 by QR · 2 by dial code" />
    <StatTile label="Awaiting confirmation" value="1" sub="on-net · confirm receipt" />
  </section>

  <section class="cols">
    <div class="card hero">
      <div class="panel-h">
        <h2 class="display">Take a payment</h2><span class="tag">smartphone</span>
      </div>
      <label class="lbl" for="amt">Amount</label>
      <div class="amount">
        <span class="cur display">$</span>
        <input id="amt" class="display tnum" bind:value={amount} inputmode="decimal" />
        <span class="ccy">USD</span>
      </div>
      <button class="btn btn-primary big"><Icon name="qr" size={18} /> Show QR to charge</button>
      <button class="btn btn-ghost big"><Icon name="phone" size={18} /> Feature phone · no internet</button>
      <p class="fine">The customer scans and pays exactly this amount. Confirms in seconds.</p>
    </div>

    <div class="card till">
      <div class="panel-h">
        <h2 class="display">Your dial code</h2>
        <button class="link"><Icon name="print" size={15} /> Print</button>
      </div>
      <div class="tillcode display">*123*1001#</div>
      <div class="qrwrap"><Qr size={150} /></div>
      <p class="fine">Tape it up. Any phone can dial it - no app, no internet.</p>
    </div>
  </section>

  <section class="card feed">
    <div class="panel-h">
      <h2 class="display">Recent payments</h2>
      <a class="link" href="#payments">View all <Icon name="arrow-right" size={15} /></a>
    </div>
    <ul class="list">
      {#each feed as row}
        <li>
          <NetworkBadge network={row.net} />
          <span class="who"><b>{row.label}</b><span class="t">{row.when}</span></span>
          <span class="amt display tnum">{row.amount}</span>
          <span class="chip {row.status === 'ok' ? 'chip-ok' : 'chip-wait'}">
            {#if row.status === 'ok'}<Icon name="check" size={13} stroke={2} /> Paid{:else}Confirm receipt{/if}
          </span>
        </li>
      {/each}
    </ul>
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
  .sub b {
    color: var(--ink);
    font-weight: 600;
  }
  .head-cta {
    padding: 11px 16px;
    white-space: nowrap;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
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
  .who .t {
    font-size: 12px;
    color: var(--muted);
  }
  .amt {
    font-weight: 600;
    font-size: 16px;
    color: var(--ink);
  }

  @media (max-width: 820px) {
    .page {
      padding: 20px 15px 96px;
    }
    h1 {
      font-size: 24px;
    }
    .stats {
      grid-template-columns: 1fr;
      gap: 12px;
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
