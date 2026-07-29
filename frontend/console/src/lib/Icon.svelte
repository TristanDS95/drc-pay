<script lang="ts" module>
  // One small stroke-icon set (currentColor, 24px grid). Named so screens stay declarative:
  // <Icon name="qr" />. No emoji anywhere in the console.
  export type IconName =
    | 'bell'
    | 'plus'
    | 'qr'
    | 'phone'
    | 'print'
    | 'check'
    | 'home'
    | 'list'
    | 'card'
    | 'cog'
    | 'sun'
    | 'moon'
    | 'refresh'
    | 'arrow-right'
    | 'exchange'
    | 'logout'

  const P: Record<IconName, string> = {
    bell: 'M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6M10.5 20a1.5 1.5 0 0 0 3 0',
    plus: 'M12 5v14M5 12h14',
    qr: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h3v3M20 14v.01M20 20v.01M17 20v.01',
    phone: 'M7 2.5h10v19H7zM10.5 18.5h3',
    print: 'M7 8V3h10v5M4 8h16v8H4zM7 14h10v6H7z',
    check: 'M20 6 9 17l-5-5',
    home: 'M4 11 12 4l8 7M6 10v9h12v-9',
    list: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01',
    card: 'M3 5h18v14H3zM3 10h18',
    cog: 'M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2',
    sun: 'M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4',
    moon: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5',
    refresh: 'M4 12a8 8 0 0 1 14-5.3L20 8M20 4v4h-4M20 12a8 8 0 0 1-14 5.3L4 16M4 20v-4h4',
    'arrow-right': 'M5 12h14M13 6l6 6-6 6',
    exchange: 'M4 9h13l-3.2-3.2M20 15H7l3.2 3.2',
    logout: 'M14 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 12h9M16 9l3 3-3 3',
  }

  const RING: Partial<Record<IconName, string>> = {
    cog: 'M12 8.8a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 0 0 0-6.4',
    moon: '',
    sun: 'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7',
  }
</script>

<script lang="ts">
  let { name, size = 20, stroke = 1.6 }: { name: IconName; size?: number; stroke?: number } = $props()
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={P[name]} />
  {#if RING[name]}<path d={RING[name]} />{/if}
</svg>
