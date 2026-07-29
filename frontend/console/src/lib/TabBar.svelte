<script lang="ts">
  import Icon from './Icon.svelte'
  import { t } from './i18n'
  let { active = 'home' }: { active?: string } = $props()
</script>

<nav class="tabbar">
  <a class:on={active === 'home'} href="#home"><Icon name="home" size={22} /><span>{$t.tab_home}</span></a>
  <a class:on={active === 'payments'} href="#payments"><Icon name="list" size={22} /><span>{$t.nav_payments}</span></a>
  <a class="fab" href="#charge" aria-label={$t.tab_charge}><Icon name="plus" size={26} stroke={1.9} /></a>
  <a class:on={active === 'customers'} href="#customers"><Icon name="card" size={22} /><span>{$t.nav_customers}</span></a>
  <a class:on={active === 'settings'} href="#settings"><Icon name="cog" size={22} /><span>{$t.nav_settings}</span></a>
</nav>

<style>
  .tabbar {
    display: none;
  }
  @media (max-width: 820px) {
    .tabbar {
      display: flex;
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      height: 66px;
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      backdrop-filter: blur(8px);
      border-top: 1px solid var(--line);
      align-items: center;
      justify-content: space-around;
      padding: 0 6px;
      padding-bottom: env(safe-area-inset-bottom);
      z-index: 30;
    }
    .tabbar a {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 3px;
      font-size: 10px;
      font-weight: 600;
      color: var(--muted);
      flex: 1;
      text-decoration: none;
    }
    .tabbar a.on {
      color: var(--brand-text);
    }
    .tabbar .fab {
      background: var(--brand);
      color: var(--brand-ink);
      width: 52px;
      height: 52px;
      border-radius: 16px;
      display: grid;
      place-items: center;
      margin-top: -18px;
      box-shadow: var(--brand-glow);
      flex: none;
    }
  }
</style>
