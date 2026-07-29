<script lang="ts">
  import { onMount } from 'svelte'
  import Mark from '../lib/Mark.svelte'
  import Wordmark from '../lib/Wordmark.svelte'
  import Icon from '../lib/Icon.svelte'
  import { api, ApiError } from '../lib/api'
  import { login } from '../lib/session'
  import { t, toggleLang, lang } from '../lib/i18n'
  import { theme, toggleTheme } from '../lib/theme'
  import { opName, loadProviders } from '../lib/format'

  // `reachable=false` at boot means the API itself was down - lead with that, not "wrong password".
  let { reachable = true }: { reachable?: boolean } = $props()

  let username = $state('')
  let password = $state('')
  let busy = $state(false)
  let error = $state('')
  // A login attempt's error wins; otherwise, if the API was down at boot, lead with that.
  // Derived so it re-translates when the language switches.
  const shownError = $derived(error || (reachable ? '' : $t.login_unreachable))
  let demos = $state<{ username: string; password: string; provider: string | null }[]>([])

  onMount(() => {
    loadProviders()
    // Demo chips only exist in sandbox; prod returns [] and we render nothing.
    api
      .demoCredentials()
      .then((list) => (demos = Array.isArray(list) ? list : []))
      .catch(() => (demos = []))
  })

  async function submit(user: string, pass: string) {
    if (busy) return
    busy = true
    error = ''
    try {
      await login(user.trim(), pass)
    } catch (err) {
      error = err instanceof ApiError && err.status === 0 ? $t.login_unreachable : $t.login_err
      password = ''
    } finally {
      busy = false
    }
  }
</script>

<div class="wrap">
  <div class="topbar">
    <button class="pill" onclick={toggleLang}>{$lang === 'fr' ? 'EN' : 'FR'}</button>
    <button class="pill" onclick={toggleTheme} aria-label="Toggle theme">
      <Icon name={$theme === 'dark' ? 'sun' : 'moon'} size={16} />
    </button>
  </div>

  <form class="card" onsubmit={(e) => (e.preventDefault(), submit(username, password))}>
    <div class="brand"><Mark size={34} /><Wordmark size={22} /></div>
    <h1 class="display">{$t.login_title}</h1>
    <p class="sub">{$t.login_sub}</p>

    <label class="lbl" for="u">{$t.login_user}</label>
    <input
      id="u"
      bind:value={username}
      autocomplete="username"
      autocapitalize="none"
      autocorrect="off"
      spellcheck="false"
    />

    <label class="lbl" for="p">{$t.login_pass}</label>
    <input id="p" type="password" bind:value={password} autocomplete="current-password" />

    {#if shownError}<div class="err" role="alert">{shownError}</div>{/if}

    <button class="btn btn-primary submit" type="submit" disabled={busy}>
      {busy ? $t.login_busy : $t.login_btn}
    </button>

    {#if demos.length}
      <div class="demo">
        <div class="demo-cap">{$t.login_demo}</div>
        <div class="chips">
          {#each demos as d}
            <button type="button" class="chip" onclick={() => submit(d.username, d.password)}>
              <b>{d.username}</b>
              {#if d.provider}<span class="net">{$opName(d.provider)}</span>{/if}
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </form>
</div>

<style>
  .wrap {
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: 20px;
    position: relative;
  }
  .topbar {
    position: absolute;
    top: 16px;
    right: 16px;
    display: flex;
    gap: 8px;
  }
  .pill {
    min-width: 34px;
    height: 34px;
    padding: 0 10px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    display: grid;
    place-items: center;
  }
  .pill:hover {
    color: var(--ink);
    border-color: var(--line2);
  }
  .card {
    width: 100%;
    max-width: 380px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 30px 26px;
    box-shadow: var(--shadow);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 9px;
    margin-bottom: 20px;
  }
  h1 {
    font-size: 24px;
    font-weight: 600;
    color: var(--ink);
  }
  .sub {
    font-size: 13.5px;
    color: var(--muted);
    line-height: 1.5;
    margin: 6px 0 18px;
  }
  .lbl {
    display: block;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--muted);
    margin: 12px 0 6px;
  }
  input {
    width: 100%;
    border: 1.5px solid var(--line2);
    border-radius: 12px;
    padding: 12px 14px;
    background: var(--inputbg);
    color: var(--ink);
    font-size: 16px; /* 16px min - anything smaller triggers iOS Safari zoom-on-focus */
    outline: none;
  }
  input:focus {
    border-color: var(--brand);
  }
  .err {
    margin-top: 14px;
    font-size: 13px;
    font-weight: 600;
    color: var(--danger);
    background: var(--dangerbg);
    border-radius: 10px;
    padding: 10px 12px;
  }
  .submit {
    width: 100%;
    padding: 14px;
    font-size: 15.5px;
    border-radius: 12px;
    margin-top: 18px;
  }
  .demo {
    margin-top: 18px;
    border-top: 1px solid var(--line);
    padding-top: 14px;
  }
  .demo-cap {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--muted);
  }
  .chips {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .chip {
    flex: 1;
    min-width: 90px;
    border: 1px solid var(--line2);
    background: var(--inputbg);
    border-radius: 12px;
    padding: 9px 8px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    color: var(--ink);
  }
  .chip:hover {
    border-color: var(--brand);
    color: var(--brand-text);
  }
  .chip b {
    font-size: 13px;
    font-weight: 700;
  }
  .chip .net {
    font-size: 10px;
    color: var(--muted);
  }
</style>
