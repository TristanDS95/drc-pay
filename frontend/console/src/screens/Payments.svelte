<script lang="ts">
  import StatTile from '../lib/StatTile.svelte'
  import TxRow from '../lib/TxRow.svelte'
  import { t } from '../lib/i18n'
  import { newestFirst, feedStatus, stats, refreshFeed, confirmReceipt } from '../lib/feed'
  import { splitAmount } from '../lib/format'

  let confirming = $state<Record<string, boolean>>({})
  const received = $derived(splitAmount($stats.received))

  async function confirm(id: string, received: boolean) {
    if (confirming[id]) return
    confirming = { ...confirming, [id]: true }
    await confirmReceipt(id, received)
    confirming = { ...confirming, [id]: false }
  }
</script>

<main class="page">
  <div class="pagehead">
    <h1 class="display">{$t.nav_payments}</h1>
    <p class="sub">{$t.pay_sub}</p>
  </div>

  <section class="stats">
    <StatTile label={$t.stat_received} value={'$' + received.whole} cents={received.cents} sub={$t.stat_received_sub} />
    <StatTile label={$t.stat_payments} value={String($stats.payments)} sub={$t.stat_payments_sub} />
    <StatTile label={$t.stat_awaiting} value={String($stats.awaiting)} sub={$t.stat_awaiting_sub} />
  </section>

  <section class="card list-card">
    {#if $feedStatus === 'loading'}
      <p class="empty">{$t.feed_loading}</p>
    {:else if $feedStatus === 'error'}
      <div class="empty">
        <p>{$t.err_api}</p>
        <button class="btn btn-ghost retry" onclick={refreshFeed}>{$t.retry}</button>
      </div>
    {:else if $newestFirst.length === 0}
      <p class="empty">{$t.feed_empty}</p>
    {:else}
      <ul class="list">
        {#each $newestFirst as row (row.id)}
          <TxRow {row} confirming={confirming[row.id]} onconfirm={(r) => confirm(row.id, r)} />
        {/each}
      </ul>
    {/if}
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
  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }
  .list-card {
    padding: 10px 22px;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .empty {
    text-align: center;
    color: var(--muted);
    font-size: 13.5px;
    padding: 30px 0;
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
    .pagehead h1 {
      font-size: 24px;
    }
    .stats {
      grid-template-columns: 1fr;
      gap: 12px;
    }
  }
</style>
