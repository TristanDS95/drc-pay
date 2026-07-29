<script lang="ts">
  import Icon from './Icon.svelte'
  let {
    label,
    value,
    cents = '',
    sub = '',
    positive = false,
    spark = false,
  }: {
    label: string
    value: string
    cents?: string
    sub?: string
    positive?: boolean
    spark?: boolean
  } = $props()
</script>

<div class="card stat">
  <div class="top">
    <span class="label">{label}</span>
    {#if spark}
      <svg class="spark" viewBox="0 0 60 20" fill="none" stroke="var(--brand-text)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M1 15 12 11 22 13 33 6 44 8 59 2" />
      </svg>
    {/if}
  </div>
  <div class="num display tnum">{value}{#if cents}<span class="cents">{cents}</span>{/if}</div>
  {#if sub}<div class="sub" class:positive>{#if positive}<Icon name="arrow-right" size={12} />{/if}{sub}</div>{/if}
</div>

<style>
  .stat {
    padding: 18px 20px;
  }
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .label {
    font-size: 13px;
    color: var(--muted);
    font-weight: 500;
  }
  .spark {
    width: 52px;
    height: 18px;
    opacity: 0.9;
  }
  .num {
    font-size: 34px;
    font-weight: 600;
    color: var(--ink);
    margin: 8px 0 4px;
    line-height: 1;
  }
  .cents {
    font-size: 20px;
    color: var(--muted);
  }
  .sub {
    font-size: 12.5px;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 3px;
  }
  .sub.positive {
    color: var(--pos);
  }
  .sub.positive :global(svg) {
    transform: rotate(-90deg);
  }
</style>
