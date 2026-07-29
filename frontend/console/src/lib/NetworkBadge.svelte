<script lang="ts" module>
  export type Network = 'airtel' | 'vodacom' | 'orange'
  // 'other' covers on-net / unresolved / unknown providers - a neutral badge, never a crash.
  const STYLE: Record<Network | 'other', { bg: string; fg: string; letter: string }> = {
    airtel: { bg: '#E4002B', fg: '#fff', letter: 'A' },
    vodacom: { bg: '#e60000', fg: '#fff', letter: 'V' },
    orange: { bg: '#ff7900', fg: '#111', letter: 'O' },
    other: { bg: 'var(--chip)', fg: 'var(--muted)', letter: '·' },
  }
</script>

<script lang="ts">
  let {
    network,
    size = 38,
    letter,
  }: { network: Network | 'other'; size?: number; letter?: string } = $props()
  const s = $derived(STYLE[network])
</script>

<span
  class="net display"
  style="width:{size}px;height:{size}px;border-radius:{Math.round(size * 0.29)}px;background:{s.bg};color:{s.fg};font-size:{Math.round(size * 0.4)}px"
  aria-hidden="true">{letter ?? s.letter}</span>

<style>
  .net {
    display: grid;
    place-items: center;
    font-weight: 700;
    flex: none;
  }
</style>
