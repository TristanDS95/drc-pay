<script lang="ts">
  import NetworkBadge from '../lib/NetworkBadge.svelte'
  import { t } from '../lib/i18n'
  import { customers, feedStatus, refreshFeed } from '../lib/feed'
  import { opName, providerToNetwork, formatMsisdn, money } from '../lib/format'
</script>

<main class="page">
  <div class="pagehead">
    <h1 class="display">{$t.nav_customers}</h1>
    <p class="sub">{$t.cust_sub}</p>
  </div>

  <section class="card list-card">
    {#if $feedStatus === 'loading'}
      <p class="empty">{$t.feed_loading}</p>
    {:else if $feedStatus === 'error'}
      <div class="empty">
        <p>{$t.err_api}</p>
        <button class="btn btn-ghost retry" onclick={refreshFeed}>{$t.retry}</button>
      </div>
    {:else if $customers.length === 0}
      <p class="empty">{$t.cust_empty}</p>
    {:else}
      <ul class="list">
        {#each $customers as c (c.msisdn)}
          <li class="row">
            <NetworkBadge network={providerToNetwork(c.provider)} />
            <span class="who">
              <b>{formatMsisdn(c.msisdn)}</b>
              <span class="tt">{$opName(c.provider)} · {$t.cust_count(c.count)}</span>
            </span>
            <span class="total display tnum">{money((c.totalMinor / 100).toFixed(2), c.currency)}</span>
          </li>
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
  .list-card {
    padding: 10px 22px;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .row {
    display: grid;
    grid-template-columns: 38px 1fr auto;
    align-items: center;
    gap: 14px;
    padding: 13px 4px;
    border-top: 1px solid var(--line);
  }
  .row:first-child {
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
  .total {
    font-weight: 600;
    font-size: 16px;
    color: var(--ink);
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
  }
</style>
