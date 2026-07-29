<script lang="ts">
  import Mark from './Mark.svelte'
  import Wordmark from './Wordmark.svelte'
  import Icon from './Icon.svelte'
  import { theme, toggleTheme } from './theme'
  import { t, lang, toggleLang } from './i18n'
  import { logout } from './session'
  import type { Merchant } from './types'

  let { merchant, active = 'Overview' }: { merchant: Merchant; active?: string } = $props()
  const items = $derived([
    { id: 'Overview', label: $t.nav_overview },
    { id: 'Payments', label: $t.nav_payments },
    { id: 'Customers', label: $t.nav_customers },
    { id: 'Settings', label: $t.nav_settings },
  ])
</script>

<header class="nav">
  <a class="brand" href="#overview"><Mark size={30} /><Wordmark size={19} /></a>
  <nav class="tabs">
    {#each items as item}
      <a class:on={item.id === active} href={'#' + item.id.toLowerCase()}>{item.label}</a>
    {/each}
  </nav>
  <div class="right">
    <button class="pill" onclick={toggleLang}>{$lang === 'fr' ? 'EN' : 'FR'}</button>
    <button class="icon-btn" onclick={toggleTheme} aria-label="Toggle theme">
      <Icon name={$theme === 'dark' ? 'sun' : 'moon'} size={18} />
    </button>
    <span class="avatar display">{merchant.name.charAt(0)}</span>
    <span class="mname">{merchant.name}</span>
    <button class="icon-btn" onclick={logout} aria-label={$t.logout} title={$t.logout}>
      <Icon name="logout" size={17} />
    </button>
  </div>
</header>

<style>
  .nav {
    display: flex;
    align-items: center;
    gap: 26px;
    padding: 0 26px;
    height: 64px;
    background: color-mix(in srgb, var(--surface) 80%, transparent);
    backdrop-filter: saturate(1.2) blur(8px);
    border-bottom: 1px solid var(--line);
    position: sticky;
    top: 0;
    z-index: 20;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 9px;
    text-decoration: none;
  }
  .tabs {
    display: flex;
    gap: 4px;
    margin-left: 6px;
  }
  .tabs a {
    padding: 8px 13px;
    border-radius: 9px;
    font-size: 14px;
    font-weight: 600;
    color: var(--muted);
    text-decoration: none;
  }
  .tabs a.on {
    color: var(--ink);
    background: var(--chip);
  }
  .tabs a:hover {
    color: var(--ink);
  }
  .right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .icon-btn {
    background: none;
    border: 1px solid var(--line);
    color: var(--muted);
    width: 36px;
    height: 36px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    cursor: pointer;
  }
  .icon-btn:hover {
    color: var(--ink);
    border-color: var(--line2);
  }
  .pill {
    height: 36px;
    min-width: 38px;
    padding: 0 10px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: none;
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
  }
  .pill:hover {
    color: var(--ink);
    border-color: var(--line2);
  }
  .avatar {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: var(--brand);
    color: var(--brand-ink);
    display: grid;
    place-items: center;
    font-weight: 700;
    font-size: 15px;
  }
  .mname {
    font-size: 14px;
    font-weight: 600;
    color: var(--ink);
  }
  @media (max-width: 820px) {
    .tabs,
    .mname {
      display: none;
    }
    .nav {
      gap: 12px;
      padding: 0 16px;
      height: 56px;
    }
  }
</style>
