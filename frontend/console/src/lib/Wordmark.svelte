<script lang="ts">
  let { size = 22 }: { size?: number } = $props()
</script>

<span class="wm display" style="font-size:{size}px">Inter<span class="pay">Pay</span></span>

<style>
  .wm {
    font-weight: 600;
    color: var(--ink);
    line-height: 1;
    letter-spacing: -0.02em;
  }
  .pay {
    color: var(--brand-text);
  }
</style>
