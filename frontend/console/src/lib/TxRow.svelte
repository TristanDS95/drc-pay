<script lang="ts">
  import Icon from './Icon.svelte'
  import NetworkBadge from './NetworkBadge.svelte'
  import { t } from './i18n'
  import { opName, providerToNetwork, formatMsisdn, money, pillClass, needsConfirm } from './format'
  import type { Transaction } from './types'

  let {
    row,
    confirming = false,
    onconfirm,
  }: {
    row: Transaction
    confirming?: boolean
    onconfirm?: (received: boolean) => void
  } = $props()
</script>

<li class="row">
  <NetworkBadge network={providerToNetwork(row.customer_provider)} />
  <span class="who">
    <b>{$opName(row.customer_provider)}</b>
    <span class="tt">{formatMsisdn(row.customer_msisdn)}</span>
  </span>
  <span class="amt display tnum">{money(row.amount, row.currency)}</span>
  {#if needsConfirm(row) && onconfirm}
    <button class="btn btn-primary confirm" disabled={confirming} onclick={() => onconfirm(true)}>
      {$t.confirm_received}
    </button>
  {:else}
    <span class="chip chip-{pillClass(row.state)}">
      {#if row.state === 'payout_succeeded'}<Icon name="check" size={13} stroke={2} /> {/if}
      {$t.states[row.state]}
    </span>
  {/if}
</li>

<style>
  .row {
    display: grid;
    grid-template-columns: 38px 1fr auto auto;
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
</style>
