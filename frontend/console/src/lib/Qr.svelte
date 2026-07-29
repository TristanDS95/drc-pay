<script lang="ts">
  // A stylized QR placeholder for the mockup/overview (the real charge QR comes from the API in a
  // later phase). Deterministic module pattern with three finder squares - reads as a QR.
  let { size = 150 }: { size?: number } = $props()
  const N = 11
  const cell = 8
  function on(x: number, y: number): boolean {
    const finder = (x < 3 && y < 3) || (x > 7 && y < 3) || (x < 3 && y > 7)
    if (finder) {
      const lx = x > 7 ? x - 8 : x
      const ly = y > 7 ? y - 8 : y
      return lx === 0 || lx === 2 || ly === 0 || ly === 2 || (lx === 1 && ly === 1)
    }
    return (x * 7 + y * 13 + x * y) % 5 < 2
  }
  const rects: [number, number][] = []
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (on(x, y)) rects.push([x * cell, y * cell])
</script>

<svg viewBox="0 0 88 88" width={size} height={size} fill="var(--qr-fg)" aria-label="QR code">
  {#each rects as [x, y]}<rect {x} {y} width="7" height="7" rx="1.4" />{/each}
</svg>
