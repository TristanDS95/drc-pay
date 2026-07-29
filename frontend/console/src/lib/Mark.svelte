<script lang="ts">
  // The InterPay "Exchange" mark - two arrows passing (payment moving between networks) in a
  // coral tile. Stroke and fill are theme tokens, so it works on light and dark unchanged.
  let { size = 44 }: { size?: number } = $props()
</script>

<span
  class="mark"
  style="width:{size}px;height:{size}px;border-radius:{Math.round(size * 0.28)}px"
  aria-hidden="true"
>
  <svg viewBox="0 0 24 24" width={size * 0.58} height={size * 0.58} fill="none" stroke="var(--brand-ink)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
    <path d="M4 9h13l-3.2-3.2M20 15H7l3.2 3.2" />
  </svg>
</span>

<style>
  .mark {
    background: var(--brand);
    display: grid;
    place-items: center;
    flex: none;
  }
</style>
