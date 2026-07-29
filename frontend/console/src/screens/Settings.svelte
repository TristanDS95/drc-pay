<script lang="ts">
  import Icon from '../lib/Icon.svelte'
  import { t, lang, setLang } from '../lib/i18n'
  import { theme } from '../lib/theme'
  import { logout } from '../lib/session'
  import { opName, formatMsisdn } from '../lib/format'
  import type { Merchant } from '../lib/types'

  let { merchant }: { merchant: Merchant } = $props()

  const rows = $derived([
    { label: $t.signup_name, value: merchant.name },
    {
      label: $t.set_payout,
      value: `${$opName(merchant.settlement_provider)} · ${formatMsisdn(merchant.settlement_msisdn)}`,
    },
    { label: $t.dial_h2, value: merchant.ussd_string },
    { label: $t.set_till, value: merchant.operator_till || $t.none },
  ])
</script>

<main class="page">
  <div class="pagehead">
    <h1 class="display">{$t.nav_settings}</h1>
  </div>

  <section class="card">
    <h2 class="ch">{$t.set_profile}</h2>
    <dl class="rows">
      {#each rows as r}
        <div class="r">
          <dt>{r.label}</dt>
          <dd>{r.value}</dd>
        </div>
      {/each}
    </dl>
    <p class="note">{$t.set_readonly}</p>
  </section>

  <section class="card">
    <h2 class="ch">{$t.set_prefs}</h2>
    <div class="pref">
      <span class="pl">{$t.set_language}</span>
      <div class="seg">
        <button class:on={$lang === 'fr'} onclick={() => setLang('fr')}>Français</button>
        <button class:on={$lang === 'en'} onclick={() => setLang('en')}>English</button>
      </div>
    </div>
    <div class="pref">
      <span class="pl">{$t.set_theme}</span>
      <div class="seg">
        <button class:on={$theme === 'light'} onclick={() => theme.set('light')}>{$t.set_theme_light}</button>
        <button class:on={$theme === 'dark'} onclick={() => theme.set('dark')}>{$t.set_theme_dark}</button>
      </div>
    </div>
  </section>

  <button class="btn btn-ghost signout" onclick={logout}>
    <Icon name="logout" size={17} /> {$t.logout}
  </button>
</main>

<style>
  .page {
    width: 100%;
    max-width: 720px;
    margin: 0 auto;
    padding: 30px 26px 40px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .pagehead h1 {
    font-size: 30px;
    font-weight: 600;
    color: var(--ink);
  }
  .card {
    padding: 22px;
  }
  .ch {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin-bottom: 14px;
  }
  .rows {
    margin: 0;
  }
  .r {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 12px 0;
    border-top: 1px solid var(--line);
  }
  .r:first-child {
    border-top: none;
  }
  .r dt {
    font-size: 13.5px;
    color: var(--muted);
  }
  .r dd {
    font-size: 14px;
    font-weight: 600;
    color: var(--ink);
    margin: 0;
    text-align: right;
  }
  .note {
    font-size: 12.5px;
    color: var(--faint);
    margin-top: 14px;
    line-height: 1.5;
  }
  .pref {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 8px 0;
  }
  .pl {
    font-size: 14px;
    color: var(--ink);
    font-weight: 500;
  }
  .seg {
    display: flex;
    border: 1px solid var(--line2);
    border-radius: 10px;
    overflow: hidden;
  }
  .seg button {
    border: none;
    background: var(--surface);
    color: var(--muted);
    font-size: 13px;
    font-weight: 600;
    padding: 8px 14px;
    cursor: pointer;
  }
  .seg button.on {
    background: var(--brand);
    color: var(--brand-ink);
  }
  .signout {
    align-self: flex-start;
    padding: 11px 18px;
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
